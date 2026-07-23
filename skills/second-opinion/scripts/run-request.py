#!/usr/bin/env python3
"""run-request.py — execute a second-opinion API request with classified retries.

Usage: run-request.py [--long] [--no-stream] <provider> <request.json>
                      <output-base> [gemini-model]
  provider     kimi | openai | deepseek | xai | zai | minimax | gemini
  request.json full request body (for gemini: no model field — pass model as 4th arg)
  output-base  writes <base>-raw.json, <base>-text.md, <base>-log.txt, <base>-pid.txt
  --long       acknowledge this is a long-path request (see "The gate" below)
  --no-stream  disable streaming (see "Streaming" below); rarely wanted

Env:
  MAX_TIME     socket timeout in seconds (default 1800). Its meaning depends on
               the mode: streaming (default) makes it an IDLE timeout — the most
               dead air tolerated between chunks — while --no-stream makes it the
               total wait for the whole response. This is a socket timeout either
               way, so it never bounds a streamed run's total duration; DEADLINE
               does that.
  DEADLINE     TOTAL wall-clock budget in seconds across all attempts and
               backoffs (default: none). Set this to slightly less than the
               caller's own timeout — retries then can never overrun it. Without
               it, 4 attempts at MAX_TIME=480 can run 33 minutes inside a Bash
               call that dies at 10.
  ATTEMPTS     max attempts (default 4). Synchronous in-fork runs should use 1:
               a retry cannot fit inside the fork's budget anyway.

The gate — why this script may refuse to start
----------------------------------------------
A long request cannot run synchronously inside a skill fork: the Bash tool caps
at 10 minutes and a killed fork ORPHANS this process (it keeps running and
keeps billing). So the script refuses, with a usage_error, to start a request
that is too big or too slow for the short path unless `--long` says the caller
knows it is on the long path (main session, background). Blocking conditions:

  * request.json >= 32768 bytes, or
  * reasoning_effort is high / xhigh / max, or
  * the model's own server-side default effort is the top tier and the request
    does not set reasoning_effort (currently kimi-k3, whose /v1/models entry
    reports default_effort "max" — an unset effort there is a max-effort call,
    measured at ~460s for a 10 KB prompt vs ~90s at "low").

This is enforced here rather than in SKILL.md prose because prose gates get
skipped: the failure that motivated it was a 52 KB request started with no
MAX_TIME at all.

Stdout is EXACTLY one JSON envelope describing the outcome, so the calling agent
gets a typed result instead of parsing the log file:
  completed:   {"status":"completed","provider","model","http_status","attempts",
                "usage","text_path","chars","log_path"}
  partial:     {"status":"partial", ...same..., "detail"}   streamed run cut short
  failed:      {"status":"failed","provider","model","error_class","http_status",
                "attempts","detail","raw_path","log_path"}
  usage_error: {"status":"usage_error","detail"}

Exit codes: 0 = text extracted; 1 = failed after retries; 2 = usage/input error;
3 = partial text on disk (the review was cut short but is readable).

Streaming (default; --no-stream opts out)
-----------------------------------------
Two problems motivated it, both observed on a 51 KB high-effort review:

1. Non-streaming waits with an idle socket for the WHOLE generation, so the
   30-minute default timeout killed a legitimate request that simply needed
   longer — after generating for 30 minutes and returning nothing.
2. Everything generated before a timeout was discarded.

Streaming fixes both. urllib's timeout is per-read, so a stream that keeps
emitting chunks stays alive regardless of total duration (verified: a 48.6 s
generation completed under a 15 s timeout), and text is written to
<base>-text.md as it arrives, so an interrupted run leaves a usable partial
review rather than nothing.

MAX_TIME must still cover the SILENT phase before the first byte, and that phase
can be enormous. Measured 2026-07-21: gpt-5.6-sol at reasoning_effort=high sent
its first SSE event after 5.9 s on a small prompt but **nothing at all for over
10 minutes** on a 52 KB one, while kimi-k3 on the same 52 KB input started
streaming within 300 s. So a small MAX_TIME is NOT a safe "stall detector" — it
silently converts a slow-but-working request into a hard failure. Keep MAX_TIME
generous (the 1800 default) and use DEADLINE to bound total time, which is the
only thing that actually bounds a streamed run.

Retries: up to 4 attempts. Transient failures (429, 5xx, network, timeout,
empty/garbled body) back off ATTEMPT*15s; 429 honors a capped Retry-After.
Deterministic failures (400 bad request, 404, a genuine 401/403 auth error) fail
fast with no wasted attempts. The one exception is OpenAI's *flaky* 401
"insufficient permissions" on ~50 KB+ inputs, which is transient and IS retried;
a model the key's tier does not include (e.g. gpt-5.6-luna on some accounts)
returns that message on all 4 attempts and then fails.

Stdlib only (urllib, json, ssl) — no dependencies, no venv.
"""
import atexit
import http.client
import json
import math
import os
import signal
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

# provider -> (url template, key env var, auth style)
PROVIDERS = {
    "kimi":     ("https://api.moonshot.ai/v1/chat/completions",      "MOONSHOT_API_KEY", "bearer"),
    "openai":   ("https://api.openai.com/v1/chat/completions",       "OPENAI_API_KEY",   "bearer"),
    "deepseek": ("https://api.deepseek.com/chat/completions",        "DEEPSEEK_API_KEY", "bearer"),
    "xai":      ("https://api.x.ai/v1/chat/completions",             "XAI_API_KEY",      "bearer"),
    "zai":      ("https://api.z.ai/api/paas/v4/chat/completions",    "ZAI_API_KEY",      "bearer"),
    "minimax":  ("https://api.minimax.io/v1/chat/completions",       "MINIMAX_API_KEY",  "bearer"),
    "gemini":   ("https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                 "GEMINI_API_KEY", "goog"),
}
DEFAULT_ATTEMPTS = 4
RETRY_AFTER_CAP = 120  # seconds — never wait longer than this on a Retry-After

# Error classes that are worth retrying. "auth" is decided per-message below.
RETRYABLE = {"rate_limit", "server_error", "network", "timeout", "empty", "bad_response"}

# --- gate thresholds (see module docstring) ---
GATE_BYTES = 32768
HIGH_EFFORTS = {"high", "xhigh", "max"}
# Models that reason at the top tier unless told otherwise, so an *unset*
# reasoning_effort is a long-path request. Verified against GET /v1/models:
# kimi-k3 reports reasoning_efforts.default_effort == "max".
MAX_EFFORT_BY_DEFAULT = {"kimi-k3"}


def emit(envelope, exit_code):
    """Print exactly one JSON envelope on stdout, then exit."""
    sys.stdout.write(json.dumps(envelope) + "\n")
    sys.exit(exit_code)


def usage_error(msg):
    sys.stderr.write("run-request.py: " + msg + "\n")
    emit({"status": "usage_error", "detail": msg}, 2)


def gate_reasons(request_obj, size):
    """Why this request is long-path only, as (kind, text) pairs.

    Empty list = safe to run synchronously. The kind lets the refusal message
    suggest a remedy that actually applies: telling a caller to lower
    reasoning_effort when it is already "low" and the block is purely about size
    is noise, and noise in an error message gets acted on wrongly.
    """
    reasons = []
    if size >= GATE_BYTES:
        reasons.append(("size", "request.json is %d bytes (>= %d)" % (size, GATE_BYTES)))
    model = request_obj.get("model") or ""
    effort = request_obj.get("reasoning_effort")
    if isinstance(effort, str) and effort.lower() in HIGH_EFFORTS:
        reasons.append(("effort", "reasoning_effort=%s" % effort))
    elif effort is None and model in MAX_EFFORT_BY_DEFAULT:
        reasons.append(("effort", "%s defaults to reasoning_effort=max server-side "
                                  "and the request does not set one" % model))
    return reasons


def strip_think(text):
    """Drop <think>...</think> blocks from MiniMax M-series content.

    Unlike the other backends, which carry chain of thought in a separate
    reasoning_content/thought field the extractors already skip, MiniMax
    interleaves it INSIDE message content wrapped in <think> tags (verified
    2026-07-23 on MiniMax-M3). It is reasoning, not review — remove it. An
    unterminated block (stream cut mid-thought) drops the rest: everything
    after <think> is reasoning too.
    """
    out, i = [], 0
    while True:
        start = text.find("<think>", i)
        if start == -1:
            out.append(text[i:])
            break
        out.append(text[i:start])
        end = text.find("</think>", start)
        if end == -1:
            break
        i = end + len("</think>")
    return "".join(out).lstrip("\n")


def extract_text(provider, parsed):
    try:
        if provider == "gemini":
            parts = parsed["candidates"][0]["content"]["parts"]
            # thought parts are the model's chain of thought, not the review
            return "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return parsed["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def error_detail(parsed, raw=b""):
    """Best-effort human-readable error string from a response body."""
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or json.dumps(err))
        if err is not None:
            return str(err)
    return raw[:300].decode("utf-8", "replace") if raw else "no body"


def classify(status, parsed, raw):
    detail = error_detail(parsed, raw)
    if status == 400:
        return "bad_request", detail
    if status in (401, 403):
        return "auth", detail
    if status == 404:
        return "not_found", detail
    if status == 429:
        return "rate_limit", detail
    if 500 <= status < 600:
        return "server_error", detail
    if parsed is None:
        return "bad_response", detail
    return "client_error", detail


def retryable(error_class, detail, provider):
    if error_class in RETRYABLE:
        return True
    if error_class == "auth":
        # OpenAI's flaky 401 "insufficient permissions" is transient and passes
        # on retry; a genuine auth failure (invalid/incorrect key) is not. This
        # is an OpenAI-specific quirk — retrying it elsewhere just burns 4
        # attempts and ~90s of backoff on a real permission error.
        return provider == "openai" and "insufficient permissions" in str(detail).lower()
    return False  # bad_request, not_found, client_error


def sse_delta(provider, event):
    """Pull (text_fragment, usage) out of one decoded SSE event."""
    if provider == "gemini":
        text = ""
        for cand in event.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                if part.get("text") and not part.get("thought"):
                    text += part["text"]
        return text, event.get("usageMetadata") or {}
    choices = event.get("choices") or []
    delta = (choices[0].get("delta") or {}) if choices else {}
    # reasoning_content is the model's private chain of thought — it keeps the
    # connection alive during long thinking, but it is not the review.
    return delta.get("content") or "", event.get("usage") or {}


def stream_sse(resp, provider, text_path, logline, deadline_ts):
    """Consume an SSE body, writing text to text_path as it arrives.

    Returns (text, usage, stop) — stop is None on a clean end, else a string
    naming why it ended early. Whatever arrived before an interruption is
    already on disk and is returned, so a partial review is never lost.
    """
    chunks, usage, stop = [], {}, None
    out = open(text_path, "w")
    try:
        for raw in resp:
            if deadline_ts is not None and time.monotonic() >= deadline_ts:
                stop = "DEADLINE reached mid-stream"
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue  # skip blank lines, comments (":"), and event: fields
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except ValueError:
                continue
            piece, u = sse_delta(provider, event)
            if u:
                usage = u
            if piece:
                chunks.append(piece)
                out.write(piece)
                out.flush()  # partial output must survive a kill -9
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError,
            http.client.HTTPException) as e:
        reason = getattr(e, "reason", e)
        stop = "stream interrupted: %s" % str(reason)[:200]
    finally:
        out.close()
    text = "".join(chunks)
    logline("stream: %d chars, %d chunks%s" %
            (len(text), len(chunks), "" if stop is None else " — " + stop))
    return text, usage, stop


def backoff(attempt, retry_after, logline, deadline_ts):
    """Sleep before the next attempt. False = the deadline leaves no room for it."""
    delay = attempt * 15
    if retry_after:
        try:
            v = float(retry_after)
            # a hostile or malformed header must never reach time.sleep():
            # negative and NaN both raise ValueError there.
            if math.isfinite(v):
                delay = max(0.0, min(v, RETRY_AFTER_CAP))
        except (TypeError, ValueError):
            pass  # HTTP-date form — fall back to the computed backoff
    if deadline_ts is not None and time.monotonic() + delay >= deadline_ts:
        logline("deadline leaves no room for a %gs backoff — stopping" % delay)
        return False
    logline("backoff %gs" % delay)
    time.sleep(delay)
    return True


def main():
    flags = {"--long", "--no-stream"}
    args = [a for a in sys.argv[1:] if a not in flags]
    long_ok = "--long" in sys.argv[1:]
    stream = "--no-stream" not in sys.argv[1:]
    if len(args) < 3:
        usage_error("usage: run-request.py [--long] [--no-stream] <provider> "
                    "<request.json> <output-base> [gemini-model]")
    provider, request_path, base = args[0], args[1], args[2]
    gemini_model = args[3] if len(args) > 3 else None

    if provider not in PROVIDERS:
        usage_error("unknown provider: %s (use %s)" % (provider, "|".join(PROVIDERS)))
    url_tmpl, key_env, _auth = PROVIDERS[provider]

    try:
        max_time = float(os.environ.get("MAX_TIME", "1800"))
    except ValueError:
        usage_error("MAX_TIME must be a number")
    if not math.isfinite(max_time) or max_time <= 0:
        usage_error("MAX_TIME must be finite and > 0 (got %r)" % max_time)
    deadline_raw = os.environ.get("DEADLINE", "").strip()
    try:
        deadline = float(deadline_raw) if deadline_raw else None
    except ValueError:
        usage_error("DEADLINE must be a number")
    if deadline is not None and (not math.isfinite(deadline) or deadline <= 0):
        usage_error("DEADLINE must be finite and > 0 (got %r)" % deadline)
    try:
        max_attempts = int(os.environ.get("ATTEMPTS", str(DEFAULT_ATTEMPTS)))
    except ValueError:
        usage_error("ATTEMPTS must be an integer")
    if max_attempts < 1:
        usage_error("ATTEMPTS must be >= 1")

    raw_path, text_path, log_path = base + "-raw.json", base + "-text.md", base + "-log.txt"
    pid_path = base + "-pid.txt"

    if not os.path.isfile(request_path) or os.path.getsize(request_path) == 0:
        usage_error("request file missing or empty: " + request_path)
    try:
        with open(request_path, "rb") as f:
            body = f.read()
        request_obj = json.loads(body)
    except OSError as e:
        usage_error("cannot read request file %s (%s)" % (request_path, e))
    except ValueError as e:
        usage_error("request file is not valid JSON: %s (%s)" % (request_path, e))
    if not isinstance(request_obj, dict):
        usage_error("request file must contain a JSON object, got %s"
                    % type(request_obj).__name__)

    request_bytes = len(body)  # gate size, before any stream fields are injected
    blocked = gate_reasons(request_obj, request_bytes)
    if blocked and not long_ok:
        kinds = {kind for kind, _ in blocked}
        remedies = []
        if "size" in kinds:
            remedies.append("trim the prompt below %d bytes" % GATE_BYTES)
        if "effort" in kinds:
            remedies.append('set reasoning_effort to "low"')
        usage_error(
            "long-path request refused: %s. This cannot run synchronously in a "
            "skill fork — the Bash tool caps at 10 minutes and a killed fork "
            "orphans this process. Hand it to the main session to run in "
            "background, which must pass --long. To use the short path instead, "
            "%s." % ("; ".join(text for _, text in blocked), " and ".join(remedies)))

    key = os.environ.get(key_env)
    if not key:
        usage_error("%s not set" % key_env)

    if provider == "gemini":
        if not gemini_model:
            usage_error("gemini requires a model name as 4th arg")
        url = url_tmpl.format(model=gemini_model)
        model = gemini_model
        headers = {"Content-Type": "application/json", "x-goog-api-key": key}
        if stream:
            # Gemini streams from a different verb, and needs alt=sse to emit
            # SSE rather than a JSON array.
            url = url.replace(":generateContent", ":streamGenerateContent") + "?alt=sse"
    else:
        url = url_tmpl
        model = request_obj.get("model", "unknown")
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
        if stream:
            # Inject rather than require it in request.json, so callers cannot
            # forget it. include_usage makes the final event carry token counts.
            request_obj["stream"] = True
            request_obj.setdefault("stream_options", {"include_usage": True})
            body = json.dumps(request_obj).encode()

    # Clear outputs from any previous run at this base. Otherwise a failed rerun
    # leaves the PRIOR run's -text.md on disk, and a caller that reads the path
    # without checking the envelope gets a stale review it believes is fresh.
    for stale in (text_path, raw_path):
        try:
            os.remove(stale)
        except OSError:
            pass

    try:
        log = open(log_path, "a", encoding="utf-8")
    except OSError as e:
        usage_error("cannot write to output base %r (%s)" % (base, e))

    def logline(s):
        log.write(s + "\n")
        log.flush()

    # Record the PID so an orphan (fork killed, this process still billing) can
    # be found and killed: kill "$(cat <base>-pid.txt)". Removed on clean exit.
    try:
        with open(pid_path, "w") as f:
            f.write("%d\n" % os.getpid())

        def drop_pid_file(*_):
            try:
                os.remove(pid_path)
            except OSError:
                pass
            if _:  # arrived via signal — exit, which is what the killer asked for
                sys.exit(143)

        atexit.register(drop_pid_file)
        # atexit does NOT run on SIGTERM, and a stale PID file is worse than
        # none: PIDs get recycled, so a later `kill $(cat …-pid.txt)` could hit
        # an unrelated process. Streamed text already written stays on disk.
        signal.signal(signal.SIGTERM, drop_pid_file)
        signal.signal(signal.SIGINT, drop_pid_file)
    except (OSError, ValueError):
        pass  # a missing pid file must never stop the actual request

    started = time.monotonic()
    deadline_ts = started + deadline if deadline is not None else None
    logline("=== run %s provider=%s model=%s bytes=%d attempts<=%d %s=%gs%s%s ===" %
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), provider, model, request_bytes,
             max_attempts, "idle_timeout" if stream else "max_time", max_time,
             " deadline=%gs" % deadline if deadline is not None else "",
             (" [--long]" if long_ok else "") + ("" if stream else " [--no-stream]")))

    ctx = ssl.create_default_context()
    last = {"error_class": "unknown", "http_status": None, "detail": "no attempt made"}
    attempt = 0

    for attempt in range(1, max_attempts + 1):
        attempt_timeout = max_time
        if deadline_ts is not None:
            remaining = deadline_ts - time.monotonic()
            if remaining <= 0:
                logline("deadline exhausted before attempt %d" % attempt)
                last = {"error_class": "timeout", "http_status": None,
                        "detail": "DEADLINE of %gs exhausted after %d attempt(s)"
                                  % (deadline, attempt - 1)}
                attempt -= 1
                break
            # Never let one attempt outlive the caller's own timeout.
            attempt_timeout = min(max_time, remaining)
        logline("=== attempt %d %s (timeout %gs) ===" %
                (attempt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), attempt_timeout))
        attempt_started = time.monotonic()
        retry_after = None
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=attempt_timeout, context=ctx) as resp:
                status = resp.getcode()
                if stream:
                    text, usage, stop = stream_sse(resp, provider, text_path,
                                                   logline, deadline_ts)
                    if provider == "minimax" and "<think>" in text:
                        # tags can span SSE chunks, so strip after the join and
                        # rewrite the file so text_path matches the envelope
                        text = strip_think(text)
                        with open(text_path, "w") as f:
                            f.write(text)
                        logline("stripped <think> block: %d chars remain" % len(text))
                    if text:
                        kind = "completed" if stop is None else "partial"
                        logline("usage: %s" % json.dumps(usage))
                        logline("%s attempt %d" % (kind.upper(), attempt))
                        envelope = {"status": kind, "provider": provider, "model": model,
                                    "http_status": status, "attempts": attempt,
                                    "usage": usage, "text_path": text_path,
                                    "chars": len(text), "log_path": log_path}
                        if kind == "partial":
                            envelope["detail"] = stop
                            emit(envelope, 3)
                        emit(envelope, 0)
                    # A 200 stream that yielded no text at all — treat as empty
                    # (retryable) exactly like the non-streaming case.
                    raw = b""
                    last = {"error_class": "empty", "http_status": status,
                            "detail": stop or "stream produced no text"}
                    logline("empty: %s" % last["detail"])
                    if attempt < max_attempts and not backoff(attempt, None, logline, deadline_ts):
                        break
                    continue
                raw = resp.read()
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                raw = e.read() or b""   # can itself raise if the connection dropped;
            except Exception:           # an exception in an except block is uncatchable
                raw = b""               # by sibling handlers, so swallow it here
            retry_after = e.headers.get("Retry-After")
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError,
                http.client.HTTPException) as e:
            reason = getattr(e, "reason", e)
            is_timeout = isinstance(e, TimeoutError) or "timed out" in str(reason).lower()
            error_class = "timeout" if is_timeout else "network"
            spent = time.monotonic() - attempt_started
            logline("%s error after %.0fs: %s" % (error_class, spent, reason))
            last = {"error_class": error_class, "http_status": None, "detail": str(reason)[:300]}
            # A timeout that burned the WHOLE budget without a single byte is not
            # transient — the request simply needs longer than MAX_TIME allows,
            # and an identical retry fails identically. (Seen for real: four
            # 300 s attempts on one 52 KB gpt-5.6-sol request, ~20 min wasted.)
            if is_timeout and spent >= 0.9 * attempt_timeout:
                last["error_class"] = "timeout_budget"
                last["detail"] = ("no response within MAX_TIME=%gs. This request needs a "
                                  "larger MAX_TIME, not a retry — some backends (OpenAI on "
                                  "large high-effort inputs) send nothing at all for many "
                                  "minutes before the stream starts." % attempt_timeout)
                logline("deterministic timeout_budget — not retrying")
                break
            if attempt < max_attempts and not backoff(attempt, None, logline, deadline_ts):
                break
            continue

        with open(raw_path, "wb") as f:
            f.write(raw)
        logline("HTTP %s, %d bytes" % (status, len(raw)))

        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None

        if status == 200 and parsed is not None:
            text = extract_text(provider, parsed)
            if provider == "minimax":
                text = strip_think(text)
            if text:
                with open(text_path, "w") as f:
                    f.write(text + "\n")
                usage = parsed.get("usageMetadata") or parsed.get("usage") or {}
                logline("usage: %s" % json.dumps(usage))
                logline("SUCCESS attempt %d" % attempt)
                emit({"status": "completed", "provider": provider, "model": model,
                      "http_status": status, "attempts": attempt, "usage": usage,
                      "text_path": text_path, "chars": len(text),
                      "raw_path": raw_path, "log_path": log_path}, 0)
            error_class, detail = "empty", error_detail(parsed, raw) or "empty response text"
        else:
            error_class, detail = classify(status, parsed, raw)

        logline("%s: %s" % (error_class, detail[:300]))
        last = {"error_class": error_class, "http_status": status, "detail": detail[:300]}

        if not retryable(error_class, detail, provider):
            logline("deterministic %s — not retrying" % error_class)
            break
        if attempt < max_attempts and not backoff(attempt, retry_after, logline, deadline_ts):
            break

    logline("FAILED after %d attempt(s): %s" % (attempt, last["error_class"]))
    sys.stderr.write("run-request.py: FAILED (%s) — see %s\n" % (last["error_class"], log_path))
    failed = {"status": "failed", "provider": provider, "model": model,
              "error_class": last["error_class"], "http_status": last["http_status"],
              "attempts": attempt, "detail": last["detail"], "log_path": log_path}
    if os.path.exists(raw_path):
        failed["raw_path"] = raw_path
    emit(failed, 1)


if __name__ == "__main__":
    # The "exactly one JSON envelope on stdout" contract must hold even when
    # something unforeseen goes wrong; a bare traceback gives the calling agent
    # nothing to parse and looks indistinguishable from a hang.
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - deliberate catch-all
        emit({"status": "failed", "error_class": "internal",
              "detail": "%s: %s" % (type(e).__name__, e)}, 1)
