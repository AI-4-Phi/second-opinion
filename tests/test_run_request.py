"""Unit tests for skills/second-opinion/scripts/run-request.py.

Stdlib only (unittest), matching the runner's own no-dependencies promise:

    python3 -m unittest discover -s tests -v

Coverage: the gate (size/effort blocking, --long override, remedy scoping),
error classification (deterministic vs transient, the OpenAI-scoped flaky-401
retry), and the envelope contract (shape and exit codes for completed /
partial / failed / usage_error), the latter end-to-end against a local HTTP
server — no network, no API keys touched.
"""
import contextlib
import http.server
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

SCRIPT = os.path.join(os.path.dirname(__file__), os.pardir,
                      "skills", "second-opinion", "scripts", "run-request.py")

spec = importlib.util.spec_from_file_location("run_request", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Env vars that could influence a run; cleared before every main() invocation
# so the host machine's real keys and settings can never leak into a test.
# Derived from PROVIDERS so new backends are scrubbed automatically. The
# SECOND_OPINION_*_MODEL overrides are honored by the *skill* layer (when it
# builds request.json), not by the runner — scrubbed anyway, defensively.
RUNNER_ENV = (["MAX_TIME", "DEADLINE", "ATTEMPTS"]
              + [key_env for _, key_env, _ in mod.PROVIDERS.values()]
              + ["SECOND_OPINION_%s_MODEL" % p.upper() for p in mod.PROVIDERS])


def run_main(argv, env=None):
    """Invoke mod.main() with controlled argv/env; return (envelope, exit_code)."""
    saved_argv = sys.argv
    saved_env = {k: os.environ.pop(k) for k in RUNNER_ENV if k in os.environ}
    os.environ.update(env or {})
    sys.argv = ["run-request.py"] + argv
    out = io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                mod.main()
            except SystemExit as e:
                code = e.code
    finally:
        sys.argv = saved_argv
        for k in RUNNER_ENV:
            os.environ.pop(k, None)
        os.environ.update(saved_env)
    return json.loads(out.getvalue()), code


class _Handler(http.server.BaseHTTPRequestHandler):
    respond = None      # set per test: callable(handler)
    requests = None     # list collecting (path, parsed_body) per test

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = None
        type(self).requests.append((self.path, parsed))
        try:
            type(self).respond(self)
        except OSError:
            pass  # client gave up (timeout tests) — not a test failure

    def send_json(self, status, obj):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_sse(self, events, delay=0.0):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for ev in events:
            payload = ev if isinstance(ev, str) else json.dumps(ev)
            self.wfile.write(("data: " + payload + "\n\n").encode())
            self.wfile.flush()
            if delay:
                time.sleep(delay)

    def log_message(self, *args):
        pass


def openai_completion(text, usage=None):
    return {"choices": [{"message": {"content": text}}], "usage": usage or {}}


class GateTests(unittest.TestCase):
    def reasons(self, obj, size=100):
        return mod.gate_reasons(obj, size)

    def kinds(self, obj, size=100):
        return {kind for kind, _ in self.reasons(obj, size)}

    def test_small_low_effort_passes(self):
        self.assertEqual(self.reasons({"model": "gpt-5.6-sol",
                                       "reasoning_effort": "low"}), [])

    def test_size_boundary(self):
        self.assertEqual(self.kinds({"model": "x"}, mod.GATE_BYTES - 1), set())
        self.assertEqual(self.kinds({"model": "x"}, mod.GATE_BYTES), {"size"})

    def test_high_efforts_block(self):
        for effort in ("high", "xhigh", "max", "HIGH"):
            self.assertEqual(self.kinds({"model": "x", "reasoning_effort": effort}),
                             {"effort"}, effort)

    def test_low_and_medium_pass(self):
        for effort in ("low", "medium"):
            self.assertEqual(self.kinds({"model": "x", "reasoning_effort": effort}),
                             set(), effort)

    def test_kimi_unset_effort_blocks(self):
        self.assertEqual(self.kinds({"model": "kimi-k3"}), {"effort"})

    def test_kimi_low_effort_passes(self):
        self.assertEqual(self.kinds({"model": "kimi-k3", "reasoning_effort": "low"}),
                         set())

    def test_other_model_unset_effort_passes(self):
        self.assertEqual(self.kinds({"model": "gpt-5.6-sol"}), set())

    def test_size_and_effort_both_reported(self):
        self.assertEqual(self.kinds({"model": "x", "reasoning_effort": "max"},
                                    mod.GATE_BYTES), {"size", "effort"})


class ClassifyTests(unittest.TestCase):
    def cls(self, status, parsed=None, raw=b"body"):
        return mod.classify(status, parsed, raw)[0]

    def test_status_mapping(self):
        self.assertEqual(self.cls(400, {}), "bad_request")
        self.assertEqual(self.cls(401, {}), "auth")
        self.assertEqual(self.cls(403, {}), "auth")
        self.assertEqual(self.cls(404, {}), "not_found")
        self.assertEqual(self.cls(429, {}), "rate_limit")
        self.assertEqual(self.cls(500, {}), "server_error")
        self.assertEqual(self.cls(503, {}), "server_error")
        self.assertEqual(self.cls(418, {}), "client_error")

    def test_non_json_body_is_bad_response(self):
        self.assertEqual(self.cls(200, None, b"<html>"), "bad_response")

    def test_detail_prefers_error_message(self):
        _, detail = mod.classify(400, {"error": {"message": "bad model"}}, b"x")
        self.assertEqual(detail, "bad model")


class RetryableTests(unittest.TestCase):
    def test_transient_classes_retry(self):
        for c in ("rate_limit", "server_error", "network", "timeout",
                  "empty", "bad_response"):
            self.assertTrue(mod.retryable(c, "", "kimi"), c)

    def test_deterministic_classes_do_not(self):
        for c in ("bad_request", "not_found", "client_error", "timeout_budget"):
            self.assertFalse(mod.retryable(c, "", "openai"), c)

    def test_flaky_401_retried_only_for_openai(self):
        detail = "You have Insufficient Permissions for this operation"
        self.assertTrue(mod.retryable("auth", detail, "openai"))
        for provider in ("kimi", "deepseek", "xai", "gemini"):
            self.assertFalse(mod.retryable("auth", detail, provider), provider)

    def test_genuine_openai_auth_error_not_retried(self):
        self.assertFalse(mod.retryable("auth", "Incorrect API key provided", "openai"))


class ExtractionTests(unittest.TestCase):
    def test_openai_shape(self):
        self.assertEqual(mod.extract_text("openai", openai_completion("hi")), "hi")

    def test_gemini_joins_parts_and_drops_thoughts(self):
        parsed = {"candidates": [{"content": {"parts": [
            {"text": "secret", "thought": True}, {"text": "a"}, {"text": "b"}]}}]}
        self.assertEqual(mod.extract_text("gemini", parsed), "ab")

    def test_malformed_returns_empty(self):
        self.assertEqual(mod.extract_text("openai", {"choices": []}), "")
        self.assertEqual(mod.extract_text("gemini", {}), "")

    def test_sse_delta_openai_ignores_reasoning(self):
        text, usage = mod.sse_delta("openai", {"choices": [{"delta": {
            "reasoning_content": "thinking...", "content": "out"}}],
            "usage": {"total_tokens": 3}})
        self.assertEqual((text, usage), ("out", {"total_tokens": 3}))

    def test_sse_delta_gemini_drops_thought_parts(self):
        text, _ = mod.sse_delta("gemini", {"candidates": [{"content": {"parts": [
            {"text": "x", "thought": True}, {"text": "y"}]}}]})
        self.assertEqual(text, "y")


class BackoffTests(unittest.TestCase):
    def go(self, attempt=1, retry_after=None, deadline_ts=None):
        sleeps = []
        with mock.patch.object(mod.time, "sleep", sleeps.append):
            ok = mod.backoff(attempt, retry_after, lambda s: None, deadline_ts)
        return ok, sleeps

    def test_default_backoff_scales_with_attempt(self):
        ok, sleeps = self.go(attempt=2)
        self.assertTrue(ok)
        self.assertEqual(sleeps, [30])

    def test_retry_after_honored_and_capped(self):
        self.assertEqual(self.go(retry_after="5")[1], [5.0])
        self.assertEqual(self.go(retry_after="9999")[1], [mod.RETRY_AFTER_CAP])

    def test_hostile_retry_after_never_reaches_sleep(self):
        for bad in ("-5", "nan", "inf", "soon", None):
            ok, sleeps = self.go(attempt=1, retry_after=bad)
            self.assertTrue(ok)
            self.assertEqual(len(sleeps), 1)
            self.assertGreaterEqual(sleeps[0], 0)

    def test_deadline_with_no_room_stops(self):
        ok, sleeps = self.go(attempt=4, deadline_ts=time.monotonic() + 1)
        self.assertFalse(ok)
        self.assertEqual(sleeps, [])


class EnvelopeTests(unittest.TestCase):
    """Exit codes and envelope shapes, end-to-end against a local server."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.base = os.path.join(self.dir.name, "out")

    def write_request(self, obj, pad_to=0):
        path = os.path.join(self.dir.name, "request.json")
        raw = json.dumps(obj)
        if pad_to and len(raw) < pad_to:
            obj = dict(obj, padding="x" * (pad_to - len(raw)))
            raw = json.dumps(obj)
        with open(path, "w") as f:
            f.write(raw)
        return path

    def start_server(self, respond):
        _Handler.respond = staticmethod(respond)
        _Handler.requests = []
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def stop():
            server.shutdown()
            server.server_close()  # joins handler threads (block_on_close), so
            # no handler can still be mutating _Handler.* when the next test
            # rebinds those class attributes
        self.addCleanup(stop)
        return "http://127.0.0.1:%d" % server.server_address[1]

    def patch_provider(self, provider, url):
        _, key_env, auth = mod.PROVIDERS[provider]
        return mock.patch.dict(mod.PROVIDERS, {provider: (url, key_env, auth)})

    # --- usage errors (exit 2) ---

    def assert_usage_error(self, argv, env=None, detail_contains=""):
        envelope, code = run_main(argv, env)
        self.assertEqual(code, 2)
        self.assertEqual(envelope["status"], "usage_error")
        self.assertIn(detail_contains, envelope["detail"])
        return envelope

    def test_missing_args(self):
        self.assert_usage_error(["kimi"], detail_contains="usage:")

    def test_unknown_provider(self):
        req = self.write_request({"model": "x"})
        self.assert_usage_error(["frontier", req, self.base],
                                detail_contains="unknown provider")

    def test_missing_request_file(self):
        self.assert_usage_error(["kimi", os.path.join(self.dir.name, "nope.json"),
                                 self.base], detail_contains="missing or empty")

    def test_empty_request_file(self):
        path = os.path.join(self.dir.name, "empty.json")
        open(path, "w").close()
        self.assert_usage_error(["kimi", path, self.base],
                                detail_contains="missing or empty")

    def test_request_must_be_json_object(self):
        path = os.path.join(self.dir.name, "request.json")
        with open(path, "w") as f:
            f.write('["not", "an", "object"]')
        self.assert_usage_error(["kimi", path, self.base],
                                detail_contains="JSON object")

    def test_bad_env_numbers(self):
        req = self.write_request({"model": "x", "reasoning_effort": "low"})
        self.assert_usage_error(["kimi", req, self.base], {"MAX_TIME": "soon"},
                                "MAX_TIME")
        self.assert_usage_error(["kimi", req, self.base], {"MAX_TIME": "-1"},
                                "MAX_TIME")
        self.assert_usage_error(["kimi", req, self.base], {"DEADLINE": "nan"},
                                "DEADLINE")
        self.assert_usage_error(["kimi", req, self.base], {"ATTEMPTS": "0"},
                                "ATTEMPTS")

    def test_missing_key_named_in_error(self):
        req = self.write_request({"model": "kimi-k3", "reasoning_effort": "low"})
        self.assert_usage_error(["kimi", req, self.base],
                                detail_contains="MOONSHOT_API_KEY not set")

    def test_gemini_requires_model_arg(self):
        req = self.write_request({"contents": []})
        self.assert_usage_error(["gemini", req, self.base],
                                {"GEMINI_API_KEY": "k"},
                                detail_contains="model name as 4th arg")

    # --- the gate (also exit 2, and --long overrides it) ---

    def test_gate_refuses_oversized_request(self):
        req = self.write_request({"model": "gpt-5.6-sol"}, pad_to=mod.GATE_BYTES)
        env = {"OPENAI_API_KEY": "k"}
        envelope = self.assert_usage_error(["openai", req, self.base], env,
                                           "long-path request refused")
        # remedy scoping: a size-only block must not suggest lowering effort
        self.assertIn("trim the prompt", envelope["detail"])
        self.assertNotIn("reasoning_effort", envelope["detail"])

    def test_gate_refuses_high_effort(self):
        # provider/key match the request body, so this refusal can only be the
        # gate — not a later provider or key check reached in a different order
        req = self.write_request({"model": "gpt-5.6-sol", "reasoning_effort": "high"})
        envelope = self.assert_usage_error(
            ["openai", req, self.base], {"OPENAI_API_KEY": "k"},
            detail_contains="long-path request refused")
        self.assertIn('set reasoning_effort to "low"', envelope["detail"])

    def test_gate_refuses_kimi_unset_effort(self):
        req = self.write_request({"model": "kimi-k3"})
        envelope = self.assert_usage_error(
            ["kimi", req, self.base], {"MOONSHOT_API_KEY": "k"},
            detail_contains="long-path request refused")
        self.assertIn('set reasoning_effort to "low"', envelope["detail"])

    def test_long_flag_overrides_gate(self):
        req = self.write_request({"model": "kimi-k3"})  # unset effort would block
        # passes the gate, then fails on the (absent) key — indirect but
        # sufficient proof that --long disabled the gate
        envelope = self.assert_usage_error(["--long", "kimi", req, self.base],
                                           detail_contains="MOONSHOT_API_KEY not set")
        self.assertNotIn("long-path request refused", envelope["detail"])

    # --- completed / partial / failed against a live local server ---

    def test_completed_non_streaming(self):
        url = self.start_server(
            lambda h: h.send_json(200, openai_completion("the review",
                                                         {"total_tokens": 9})))
        req = self.write_request({"model": "gpt-5.6-terra", "reasoning_effort": "low"})
        with self.patch_provider("openai", url):
            envelope, code = run_main(["--no-stream", "openai", req, self.base],
                                      {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertEqual(envelope["status"], "completed")
        for key in ("provider", "model", "http_status", "attempts", "usage",
                    "text_path", "chars", "log_path", "raw_path"):
            self.assertIn(key, envelope)
        self.assertEqual(envelope["model"], "gpt-5.6-terra")
        self.assertEqual(envelope["usage"], {"total_tokens": 9})
        self.assertEqual(envelope["chars"], len("the review"))
        with open(envelope["text_path"]) as f:
            self.assertEqual(f.read(), "the review\n")
        # The pid file (the orphan-kill mechanism) must have been written with
        # this process's PID. Its removal happens via atexit/SIGTERM handlers,
        # which cannot fire here: the test catches SystemExit in-process, so
        # the interpreter never actually exits.
        with open(self.base + "-pid.txt") as f:
            self.assertEqual(int(f.read()), os.getpid())

    def test_completed_streaming_injects_stream_fields(self):
        url = self.start_server(lambda h: h.send_sse([
            {"choices": [{"delta": {"content": "Hello "}}]},
            {"choices": [{"delta": {"content": "world"}}],
             "usage": {"total_tokens": 7}},
            "[DONE]"]))
        req = self.write_request({"model": "kimi-k3", "reasoning_effort": "low"})
        with self.patch_provider("kimi", url):
            envelope, code = run_main(["kimi", req, self.base],
                                      {"MOONSHOT_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertEqual(envelope["status"], "completed")
        self.assertEqual(envelope["chars"], len("Hello world"))
        self.assertEqual(envelope["usage"], {"total_tokens": 7})
        sent = _Handler.requests[0][1]
        self.assertIs(sent["stream"], True)
        self.assertEqual(sent["stream_options"], {"include_usage": True})

    def test_gemini_streaming_rewrites_url(self):
        url = self.start_server(lambda h: h.send_sse([
            {"candidates": [{"content": {"parts": [
                {"text": "ignored", "thought": True}, {"text": "review"}]}}],
             "usageMetadata": {"totalTokenCount": 4}}]))
        req = self.write_request({"contents": []})
        tmpl = url + "/v1beta/models/{model}:generateContent"
        with self.patch_provider("gemini", tmpl):
            envelope, code = run_main(
                ["gemini", req, self.base, "gemini-2.5-pro"],
                {"GEMINI_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertEqual(envelope["status"], "completed")
        self.assertEqual(envelope["model"], "gemini-2.5-pro")
        self.assertEqual(envelope["chars"], len("review"))
        path = _Handler.requests[0][0]
        self.assertIn(":streamGenerateContent", path)
        self.assertIn("alt=sse", path)

    def test_partial_when_stream_is_cut(self):
        def respond(h):
            h.send_sse([{"choices": [{"delta": {"content": "three findings..."}}]}])
            time.sleep(3)   # well past the 1 s deadline, so a loaded machine
            h.send_sse([])  # cannot deliver this before the runner gives up
        url = self.start_server(respond)
        req = self.write_request({"model": "kimi-k3", "reasoning_effort": "low"})
        with self.patch_provider("kimi", url):
            envelope, code = run_main(["kimi", req, self.base],
                                      {"MOONSHOT_API_KEY": "k", "DEADLINE": "1",
                                       "ATTEMPTS": "1"})
        self.assertEqual(code, 3)
        self.assertEqual(envelope["status"], "partial")
        self.assertIn("detail", envelope)
        with open(envelope["text_path"]) as f:
            self.assertEqual(f.read(), "three findings...")

    def test_failed_deterministic_no_retry(self):
        url = self.start_server(
            lambda h: h.send_json(400, {"error": {"message": "bad model name"}}))
        req = self.write_request({"model": "nope", "reasoning_effort": "low"})
        with self.patch_provider("openai", url):
            envelope, code = run_main(["openai", req, self.base],
                                      {"OPENAI_API_KEY": "k", "ATTEMPTS": "4"})
        self.assertEqual(code, 1)
        self.assertEqual(envelope["status"], "failed")
        self.assertEqual(envelope["error_class"], "bad_request")
        self.assertEqual(envelope["attempts"], 1)  # deterministic → no retries
        self.assertIn("bad model name", envelope["detail"])
        self.assertEqual(len(_Handler.requests), 1)

    def test_transient_error_retried_to_success(self):
        state = {"calls": 0}

        def respond(h):
            state["calls"] += 1
            if state["calls"] == 1:
                h.send_json(500, {"error": {"message": "upstream blew up"}})
            else:
                h.send_json(200, openai_completion("second try worked"))
        url = self.start_server(respond)
        req = self.write_request({"model": "gpt-5.6-terra", "reasoning_effort": "low"})
        with self.patch_provider("openai", url), \
                mock.patch.object(mod.time, "sleep"):
            envelope, code = run_main(["--no-stream", "openai", req, self.base],
                                      {"OPENAI_API_KEY": "k", "ATTEMPTS": "2"})
        self.assertEqual(code, 0)
        self.assertEqual(envelope["status"], "completed")
        self.assertEqual(envelope["attempts"], 2)
        self.assertEqual(state["calls"], 2)

    def test_transient_errors_to_exhaustion(self):
        url = self.start_server(
            lambda h: h.send_json(500, {"error": {"message": "still down"}}))
        req = self.write_request({"model": "gpt-5.6-terra", "reasoning_effort": "low"})
        with self.patch_provider("openai", url), \
                mock.patch.object(mod.time, "sleep"):
            envelope, code = run_main(["--no-stream", "openai", req, self.base],
                                      {"OPENAI_API_KEY": "k", "ATTEMPTS": "2"})
        self.assertEqual(code, 1)
        self.assertEqual(envelope["status"], "failed")
        self.assertEqual(envelope["error_class"], "server_error")
        self.assertEqual(envelope["attempts"], 2)
        self.assertEqual(len(_Handler.requests), 2)

    def test_network_error_envelope(self):
        # a port that was just bound and closed — nothing is listening
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        req = self.write_request({"model": "gpt-5.6-terra", "reasoning_effort": "low"})
        with self.patch_provider("openai", "http://127.0.0.1:%d/v1" % port):
            envelope, code = run_main(["openai", req, self.base],
                                      {"OPENAI_API_KEY": "k", "ATTEMPTS": "1"})
        self.assertEqual(code, 1)
        self.assertEqual(envelope["status"], "failed")
        self.assertEqual(envelope["error_class"], "network")

    def test_timeout_budget_not_retried(self):
        def respond(h):
            time.sleep(2)  # never answer within MAX_TIME
            h.send_json(200, openai_completion("too late"))
        url = self.start_server(respond)
        req = self.write_request({"model": "gpt-5.6-terra", "reasoning_effort": "low"})
        with self.patch_provider("openai", url):
            envelope, code = run_main(["openai", req, self.base],
                                      {"OPENAI_API_KEY": "k", "MAX_TIME": "0.5",
                                       "ATTEMPTS": "4"})
        self.assertEqual(code, 1)
        self.assertEqual(envelope["status"], "failed")
        self.assertEqual(envelope["error_class"], "timeout_budget")
        self.assertEqual(envelope["attempts"], 1)  # deterministic — one attempt
        self.assertIn("larger MAX_TIME", envelope["detail"])

    def test_gemini_no_stream_uses_plain_endpoint(self):
        url = self.start_server(lambda h: h.send_json(200, {
            "candidates": [{"content": {"parts": [{"text": "review"}]}}],
            "usageMetadata": {"totalTokenCount": 4}}))
        req = self.write_request({"contents": []})
        tmpl = url + "/v1beta/models/{model}:generateContent"
        with self.patch_provider("gemini", tmpl):
            envelope, code = run_main(
                ["--no-stream", "gemini", req, self.base, "gemini-2.5-pro"],
                {"GEMINI_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertEqual(envelope["status"], "completed")
        self.assertEqual(envelope["chars"], len("review"))
        path = _Handler.requests[0][0]
        self.assertIn(":generateContent", path)
        self.assertNotIn("streamGenerateContent", path)
        self.assertNotIn("alt=sse", path)

    def test_pid_file_removed_on_clean_exit(self):
        # The orphan-kill contract needs a real process exit (atexit), so run
        # the runner as an actual child, pointing its provider at our server.
        url = self.start_server(
            lambda h: h.send_json(200, openai_completion("done")))
        req = self.write_request({"model": "gpt-5.6-terra", "reasoning_effort": "low"})
        driver = (
            "import importlib.util, sys\n"
            "script, url, req, base = sys.argv[1:5]\n"
            "spec = importlib.util.spec_from_file_location('rr', script)\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "m.PROVIDERS['openai'] = (url, 'OPENAI_API_KEY', 'bearer')\n"
            "sys.argv = ['run-request.py', '--no-stream', 'openai', req, base]\n"
            "m.main()\n")
        env = {k: v for k, v in os.environ.items() if k not in RUNNER_ENV}
        env["OPENAI_API_KEY"] = "k"
        proc = subprocess.run(
            [sys.executable, "-c", driver, os.path.abspath(SCRIPT), url,
             req, self.base],
            capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["status"], "completed")
        self.assertFalse(os.path.exists(self.base + "-pid.txt"),
                         "pid file must be removed on clean exit")

    def test_failed_rerun_clears_stale_text(self):
        url = self.start_server(
            lambda h: h.send_json(200, openai_completion("fresh review")))
        req = self.write_request({"model": "gpt-5.6-terra", "reasoning_effort": "low"})
        env = {"OPENAI_API_KEY": "k"}
        with self.patch_provider("openai", url):
            envelope, code = run_main(["--no-stream", "openai", req, self.base], env)
        self.assertEqual(code, 0)
        text_path = envelope["text_path"]
        self.assertTrue(os.path.exists(text_path))

        _Handler.respond = staticmethod(
            lambda h: h.send_json(400, {"error": {"message": "nope"}}))
        with self.patch_provider("openai", url):
            envelope, code = run_main(["--no-stream", "openai", req, self.base], env)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(text_path),
                         "a failed rerun must not leave the prior run's review")


if __name__ == "__main__":
    unittest.main()
