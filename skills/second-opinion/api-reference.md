# API Reference (Kimi, OpenAI, DeepSeek, xAI, z.AI, MiniMax, Gemini)

All backends are called through the shipped runner (stdlib Python, no deps).

**Build mode — the documented interface.** The runner composes the request
body itself from a prompt file:

    python3 scripts/run-request.py [--long] [--no-stream] --prompt-file <path> [--model <id>] [--effort <level>] <provider> <output-base>

- `provider`: `kimi` | `openai` | `deepseek` | `xai` | `zai` | `minimax` | `gemini`
- Writes `<output-base>-raw.json`, `-text.md`, `-log.txt`, `-pid.txt`, and
  `-envelope.json` (see "Reading a run's outcome from disk" below); build
  mode additionally writes `-request.json` — the body it built, kept for
  debugging and as the exemplar body shape for driving legacy mode by hand.
  Written only after the gate and key checks pass, so a gate-refused or
  missing-key run leaves no `-request.json`.
- `--long`: assert this is a long-path run (main session, background).
  Required for anything the gate blocks — see "Envelope, gate, and orphan
  cleanup" below.
- `--no-stream`: disable streaming — see "Streaming" below; rarely wanted.
- `--model` / `--effort`: see "Model and effort resolution" below.

**Legacy mode — the bring-your-own-body escape hatch.** Skip `--prompt-file`
and hand the runner a pre-built request.json instead:

    python3 scripts/run-request.py [--long] [--no-stream] <provider> <request.json> <output-base> [gemini-model]

Legacy mode never reads `SECOND_OPINION_<PROVIDER>_MODEL` — the model comes
entirely from what you pass in. For every OpenAI-compatible backend that means
a `"model"` field inside request.json; **gemini is different: its
request.json carries NO `"model"` field at all** — the model goes in the URL,
which the runner builds from the **mandatory 4th argument**, not from the
body (a gemini legacy call with only 3 positionals is a usage_error). Any
build-mode run's `<base>-request.json` is the exemplar body shape for
hand-driving legacy mode — with the old hand-built-body recipes retired (see
"Building a request" below), it is the only body example left in this repo.

## Model and effort resolution (build mode)

`--model` → `SECOND_OPINION_<PROVIDER>_MODEL` (empty or whitespace-only counts
as unset) → `DEFAULT_MODELS` in the runner — the authoritative home for
per-provider defaults (`scripts/run-request.py`, verified 2026-07 against
each provider's `GET /models`). Only `--prompt-file` runs resolve this way;
legacy mode never reads the env var.

`--effort` takes `low`, `medium`, `high`, `xhigh`, or `max`, case-insensitive,
lowercased into the body before it is sent. Per-provider tier validity is
**not** validated here — e.g. `kimi-k3` rejecting `"medium"` (see its quirks
below) surfaces as the provider's own 400, classified `bad_request`, rather
than as a decay-prone table baked into the runner.

**Unset effort is not always neutral.** If `--effort` is omitted and the
resolved model is in `MAX_EFFORT_BY_DEFAULT` (currently just `kimi-k3`, whose
server-side default is `"max"`), the runner injects `"low"`. This is
**model-keyed, not provider-keyed**: an override to some other model via
`SECOND_OPINION_KIMI_MODEL` is not covered, so nothing is injected for it —
set `--effort` explicitly whenever overriding a default model.

`--effort` on gemini is a usage_error — gemini has no such API parameter.

## Env vars

Apply identically to both modes.

| Var | Default | Meaning |
|---|---|---|
| `MAX_TIME` | 1800 | **Socket** timeout, seconds. Streaming (the default) makes this an *idle* timeout — max dead air between chunks. `--no-stream` makes it the total wait. |
| `DEADLINE` | none | **Total** wall clock across all attempts and backoffs. |
| `ATTEMPTS` | 4 | Max attempts. |

`MAX_TIME` alone does not bound the run: 4 attempts at `MAX_TIME=480` plus
backoff is 33 minutes, inside a Bash call that dies at 10. **`DEADLINE` is what
actually bounds it** — set it just under the caller's own timeout. It caps each
attempt to the time remaining and skips a backoff that would overrun, so the
runner always returns an envelope before the caller gives up.

The sanctioned flow is one path, always: every plugin-launched review runs
`--long DEADLINE=5400` as a background task, with `MAX_TIME` (1800) and
`ATTEMPTS` (4) left at their defaults — 90 minutes of room for the retries a
foreground call's 10-minute budget could never fit, bounded by `DEADLINE`.
The same numbers hold when a human drives the runner directly. `--long` is
mandatory on this path — without it the gate refuses anything it classifies
as too big or too slow for a foreground call (see "Envelope, gate, and orphan
cleanup" below).

**Do not shrink `MAX_TIME` to "detect stalls".** It looks like an idle timeout
once streaming is on, but it also governs the silent wait before the first byte,
and that wait can be enormous (measured below). A small value converts a
slow-but-working request into a hard failure. `DEADLINE` is the correct bound.
Learned the hard way: `MAX_TIME=300` on a 52 KB `gpt-5.6-sol` review produced
four identical 300 s timeouts and ~20 wasted minutes. The runner now classifies
that case as `timeout_budget` and refuses to retry it.

Retries: `ATTEMPT*15`-second backoff (429 honors a capped `Retry-After`).

## Reading a run's outcome from disk

Stdout reaches only the process that launched the runner, so a launcher that dies
first takes the outcome with it. The same envelope is therefore written to
`<output-base>-envelope.json`, atomically, at the moment a terminal outcome is
reached and before stdout — so a reader who finds the process gone still finds the
outcome. If you hold the stdout envelope, it is authoritative for the process you
launched; the file is for readers who lost that channel.

| On disk, for a known output base | What it means |
|---|---|
| Fresh `-envelope.json` | A terminal outcome was reached (not necessarily that the process has exited — the file lands just before stdout). Read `status` **first**: `completed`/`partial` carry `text_path` and `chars`, `failed` carries `error_class`, `usage_error` means **no request was attempted**. |
| No envelope, `-pid.txt` present | Probably still running. Evidence, not proof: confirm with `kill -0 <pid>`, and treat a pid file older than `DEADLINE` as stale — `SIGKILL` leaves it behind. |
| No envelope, no `-pid.txt` | Outcome unknown: never started, the pid write failed, the run was terminated (SIGTERM/SIGINT/SIGKILL all exit without reaching the envelope), or the envelope write failed. `-log.txt` usually says which, but a run can die before it opens. |

The file describes the **latest invocation** at that output base — a previous run's
envelope is removed as soon as a new run knows its base, and `-text.md` from an
earlier run can still be sitting there, which is why `status` comes first. Use a
fresh output base per invocation if you need to tie an envelope to a specific run.
The write is best-effort: if it fails, stdout and the exit code are unaffected and a
note goes to stderr.

## Streaming (default) and partial output

The runner streams SSE unless given `--no-stream`, and writes text to
`<base>-text.md` as it arrives. Two consequences:

**Long generations stop timing out.** urllib's `timeout` is per-read, so a
stream that keeps emitting chunks survives any total duration — verified: a
48.6 s generation completed under a 15 s socket timeout. Non-streaming waits
with an idle socket for the entire generation, which is why a 51 KB
`reasoning_effort: high` review died at the 1800 s default *after generating for
the full 30 minutes and returning nothing*.

**But time-to-first-byte varies wildly by provider and input size**, and
`MAX_TIME` still has to cover it. Measured 2026-07-21 at `reasoning_effort: high`:

| request | `gpt-5.6-sol` | `kimi-k3` |
|---|---|---|
| small prompt | first event at 5.9 s | first event at 9.4 s |
| 52 KB review | **nothing after 10 min** | streaming within 300 s |

So Kimi starts emitting early (its reasoning tokens stream, keeping the socket
warm) while OpenAI can stay completely silent for many minutes on a large
high-effort input. Size `MAX_TIME` for the worst case — the 1800 default — and
bound the run with `DEADLINE`.

**An interrupted run leaves a usable review.** Text already received is on disk.
The runner then emits `{"status":"partial", …, "chars":N, "detail":"…"}` with
exit code **3**. That is not a failure — it is real model output that stops
early. Guidance on acting on one lives in the root README.

Wire details, if debugging: OpenAI-compatible backends take `stream: true` in
the body (the runner injects it, along with `stream_options.include_usage` so
the final event carries token counts) and emit `choices[0].delta.content`,
terminated by `data: [DONE]`. Gemini instead needs a different verb and query
param — `:streamGenerateContent?alt=sse` (the runner rewrites the URL) — and
emits `candidates[0].content.parts[].text` with no `[DONE]` sentinel.

API keys (each must be exported in the environment; the runner refuses with a
`usage_error` naming the missing var): `MOONSHOT_API_KEY`, `OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`, `XAI_API_KEY`, `ZAI_API_KEY`, `MINIMAX_API_KEY`,
`GEMINI_API_KEY`.

## Envelope, gate, and orphan cleanup

This file is the authoritative home for these three facts — one home per
fact, so they cannot drift out of sync with SKILL.md, which keeps routing and
the fork contract only. The PREPARED template in SKILL.md's final-message
contract carries deliberately compressed copies of the status table, the
reader rule, and the kill line below (three copies, acknowledged); if they
ever disagree, this file wins.

**The reader rule.** Stdout is exactly one JSON envelope describing the
outcome — parse it, never guess. The same object also lands in
`<output-base>-envelope.json` (see "Reading a run's outcome from disk" above
for the on-disk states before a terminal outcome is reached).

| status | exit | fields |
|---|---|---|
| `completed` | 0 | `provider`, `model`, `http_status`, `attempts`, `usage`, `text_path`, `chars`, `log_path` |
| `partial` | 3 | same, plus `detail` — real text on disk, cut short |
| `failed` | 1 | `provider`, `model`, `error_class`, `http_status`, `attempts`, `detail`, `raw_path`, `log_path` |
| `usage_error` | 2 | `detail` — bad argument, missing file, unset key, **or a gate refusal**; no request was attempted |

**The gate.** A foreground tool call dies at 10 minutes and orphans the
runner (it keeps running, and billing) if the request turns out to be too big
or too slow, so the runner refuses to start one as a `usage_error` prefixed
`long-path request refused: ` — unless `--long` says the caller knows it is
running in the background. Blocking conditions (any one is enough):

- the serialized request body is >= 32768 bytes;
- `reasoning_effort` is `high`, `xhigh`, or `max`;
- the resolved model is in `MAX_EFFORT_BY_DEFAULT` (currently `kimi-k3`) and
  no `reasoning_effort` was set — that model's server-side default is `max`.

The refusal names a remedy per condition it hit (trim the prompt below 32768
bytes; set `reasoning_effort` to `"low"`) — and because the sanctioned flow
(see "Env vars" above) always passes `--long`, the gate in practice only ever
faces a **direct caller**, never the plugin.

**Orphan cleanup.** A killed launcher does not kill the runner — it is a
foreground child that outlives its parent. To cancel a run, or clean up after
a launcher that died without collecting the envelope, kill the process
directly:

    kill "$(cat <output-base>-pid.txt)"

### Error classes

Deterministic — failed fast, never retried: `bad_request`, `auth`, `not_found`,
`client_error`, `timeout_budget`, `internal`.
Transient — retried up to `ATTEMPTS` times: `rate_limit`, `server_error`,
`network`, `timeout`, `empty`, `bad_response`.

`empty` = HTTP 200 with no extractable text. `bad_response` = a non-JSON body.
`timeout_budget` = the full `MAX_TIME` elapsed without a single byte, which means
the budget is too small rather than the call being unlucky — raise `MAX_TIME`
instead of retrying. `internal` = an unexpected exception in the runner itself;
the envelope still arrives so the caller never sees a bare traceback.

## OpenAI-compatible backends (Kimi, OpenAI, DeepSeek, xAI, z.AI, MiniMax)

Endpoints (the runner knows these; listed for debugging):

| Provider | Endpoint |
|---|---|
| Kimi | `https://api.moonshot.ai/v1/chat/completions` |
| OpenAI | `https://api.openai.com/v1/chat/completions` |
| DeepSeek | `https://api.deepseek.com/chat/completions` |
| xAI | `https://api.x.ai/v1/chat/completions` |
| z.AI | `https://api.z.ai/api/paas/v4/chat/completions` |
| MiniMax | `https://api.minimax.io/v1/chat/completions` |

Auth is `Authorization: Bearer $<KEY>`. Response text lives at
`.choices[0].message.content`. All current default models are native reasoning
models (usage shows `reasoning_tokens`).

### Building a request

Build mode composes the body — no manual shell templating needed (see the
usage grammar and "Model and effort resolution" at the top of this file). The
wire shapes below are exactly what it produces, kept here for debugging and
as the reference for hand-driving legacy mode. Both share one system string,
quoted once:

    "You are an expert reviewer providing a second opinion. Be specific, cite evidence, and explain your reasoning."

OpenAI-compatible backends (Kimi, OpenAI, DeepSeek, xAI, z.AI, MiniMax):

    {
      "model": "<resolved model>",
      "reasoning_effort": "<resolved effort>",
      "messages": [
        {"role": "system", "content": "<system string above>"},
        {"role": "user", "content": "<prompt file content>"}
      ]
    }

`reasoning_effort` is present only when build-mode effort resolution produced
a value (see "Model and effort resolution" above) — e.g. it is absent by
default on `gpt-5.6-sol`, present and `"low"` by default on `kimi-k3`.

Gemini's shape has no `"model"` field — see "Gemini backend" below for why:

    {
      "systemInstruction": {"parts": [{"text": "<system string above>"}]},
      "contents": [{"parts": [{"text": "<prompt file content>"}]}]
    }

The runner does not add `temperature`, `top_p`, `n`, `presence_penalty`, or
`frequency_penalty` to either shape — Kimi fixes them server-side and the
other backends do not need them here.

### Models

Verified 2026-07. To change a backend's default without editing the skill, set
`SECOND_OPINION_<PROVIDER>_MODEL` (see SKILL.md "Available Backends").

| Provider | Model | Role |
|---|---|---|
| Kimi | `kimi-k3` | flagship (**default**); 1M ctx; always-on reasoning; single tier |
| OpenAI | `gpt-5.6-sol` | OpenAI flagship |
| OpenAI | `gpt-5.6-terra` | balanced, ~gpt-5.5-level at half price |
| OpenAI | `gpt-5.6-luna` | fast/cheap (tier-gated: not enabled on every key — see the flaky-401 section) |
| OpenAI | `gpt-5.5` | prior OpenAI flagship |
| DeepSeek | `deepseek-v4-pro` | 1M ctx; supports `reasoning_effort: high`/`xhigh` |
| DeepSeek | `deepseek-v4-flash` | cheapest useful review (~$0.14/M in); 1M ctx |
| xAI | `grok-4.5` | xAI flagship; 500k ctx |
| xAI | `grok-4.3` | 1M ctx, ~half price — long documents |
| z.AI | `glm-5.2` | newest *accessible* on this endpoint's `/models` (re-verified 2026-08-16; gating note below) |
| MiniMax | `MiniMax-M3` | MiniMax flagship; `<think>` quirk below |
| MiniMax | `MiniMax-M2.7-highspeed` | faster tier |

Naming traps (verified): Kimi K3 has only the one id `kimi-k3` (do not use the
K2.x `thinking` parameter); there is no bare `gpt-5.6` (only `-sol`/`-terra`/`-luna`);
`gpt-5.5-pro` is Responses-API-only and not wired in; DeepSeek's old
`deepseek-chat`/`deepseek-reasoner` aliases are deprecated as of 2026-07-24 —
use the `deepseek-v4-*` names; ignore xAI's `grok-4.20-*`, `grok-build-*`, and
`grok-imagine-*` entries. For z.AI and MiniMax, `GET /models` on the endpoint
host lists the candidates for *your* key — but **a listing is not access**:
2026-08-16, `glm-5.3` appeared on z.AI's `/models` while every completion on a
standard API key failed with error 1220 "You do not have permission to access
glm-5.3" (at launch it was gated to the GLM Coding Plan / ZCode, with plain API
access staged to follow). So before promoting a newer id, run one live
completion on it; newest *accessible* were `glm-5.2` and `MiniMax-M3`
(re-verified 2026-08-16).

### z.AI and MiniMax quirks (verified 2026-07-23, live smoke tests)

- Both stream fine through the runner (accept the injected `stream` +
  `stream_options`) and reason by default (usage shows `reasoning_tokens`).
  Small-prompt wall clock: `glm-5.2` ~15 s, `MiniMax-M3` ~5 s.
- **MiniMax puts its chain of thought INSIDE `message.content`, wrapped in
  `<think>...</think>`** — not in the `reasoning_content` field other backends
  use. The runner strips those blocks for `provider == "minimax"` (tags can
  span SSE chunks, so it strips after the join and rewrites `-text.md`). A
  stream cut *inside* a think block therefore yields empty text, classified
  `empty`, not `partial` — correct, since no review had arrived yet.
- `reasoning_effort` support is unverified on both — omit the field there
  (defaults are sane; see latencies above). This is the fork's routing rule
  for effort, stated plainly: pass `--effort` for kimi / openai / deepseek /
  xai; omit it for gemini (the runner refuses the flag — no such API
  parameter) and for z.AI / MiniMax (`reasoning_effort` support unverified
  here, as of 2026-07-23).

### Kimi `kimi-k3` quirks

- **1M-token context** (1,048,576). `max_completion_tokens` defaults to 131072,
  settable up to 1048576.
- **Thinking is always on, and defaults to the *slowest* setting.**
  `reasoning_effort` accepts `"low"`, `"high"`, and `"max"` — there is no
  `"medium"` — and **the server default is `"max"`**. (Verified 2026-07-20 from
  `GET https://api.moonshot.ai/v1/models`, whose `kimi-k3` entry reports
  `reasoning_efforts: {valid_efforts: ["low","high","max"], default_effort: "max"}`.)
  Do not send the K2.x `thinking` parameter.
- **Always set `reasoning_effort` explicitly.** Omitting it is *not* neutral —
  it silently buys a max-effort call. Measured on one identical 10.8 KB review
  prompt (2026-07-20):

  | `reasoning_effort` | wall clock | reasoning tokens |
  |---|---|---|
  | unset (= `max`) | **462 s** | 11,595 |
  | `"low"` | **92 s** | 919 |

  Both reviews led with the same top finding, so max effort bought latency,
  not insight. Build mode closes this by default: an unset `--effort` with
  the resolved model `kimi-k3` gets `"low"` injected automatically (see
  "Model and effort resolution" above). This measurement is what the gate
  protects everyone else against — a legacy request.json (or any hand-built
  body) for `kimi-k3` with no `reasoning_effort` field trips the gate's
  "model defaults to max" condition and is refused as a foreground call (see
  "Envelope, gate, and orphan cleanup" above).
- **Fixed sampling params:** `temperature=1.0`, `top_p=0.95`, `n=1`,
  `presence_penalty=0`, `frequency_penalty=0` are fixed server-side — omit them
  from the request (the standard request shape above already does).
- **Pricing:** $3.00/M cache-miss input, $0.30/M cache-hit input, $15.00/M
  output — the priciest backend, and always-reasoning, so slower/dearer than the
  flash/free tiers. Route quick or cheap checks elsewhere.

### `reasoning_effort`

OpenAI gpt-5.x and DeepSeek v4-pro accept `"reasoning_effort"` in the request
body (`low`/`medium`/`high`; DeepSeek pro also `xhigh`). Kimi `kimi-k3` accepts
`low`/`high`/`max` (no `medium`) and always reasons regardless.

Defaults differ in a way that matters: OpenAI and DeepSeek default to a middle
tier, so omitting the field is safe there. **`kimi-k3` defaults to `max`**
server-side, so an unset effort in a legacy or hand-built body is a max-effort
call — build mode's default resolution covers this for `kimi-k3` (see "Model
and effort resolution" above), but always set it explicitly when hand-building
a body or overriding to a different model.

Raise effort for debugging, edge-case analysis, and hard problems, and note that
a high-effort setting on a large input routinely runs 5–30 minutes — which is
why `reasoning_effort` in `high`/`xhigh`/`max` is one of the gate's blocking
conditions (see "Envelope, gate, and orphan cleanup" above).

### Flaky OpenAI 401 on large inputs (retried only for `openai`)

On inputs from ~50 KB up, the OpenAI API intermittently returns
`"You have insufficient permissions for this operation"` even though the key
has access (verified 2026-07-15: identical request went pass/fail/pass). The
runner classifies this as a *transient* `auth` error and retries it (unlike a
genuine "incorrect API key", which fails fast). A model your key's tier does
not include returns the same message deterministically — if all attempts fail
identically, it's real, not flaky (observed with `gpt-5.6-luna` on a key whose
tier excluded it; access is account-dependent, so test on yours).

This retry is **scoped to `provider == "openai"`**. It is an OpenAI quirk, and
applying it everywhere meant a genuine permission error from Kimi/DeepSeek/xAI
whose message happened to contain that phrase burned every attempt plus backoff
for nothing.

## Gemini backend

Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent`
— the model goes in the URL, not the body (see "Building a request" above for
the exact shape, and the legacy-mode paragraph at the top of this file for why
a legacy gemini call needs the model as its 4th argument). The key travels in
the `x-goog-api-key` header, not the URL, so it stays out of `ps`/logs.

Response text can span multiple `parts` (thinking models emit
`thoughtSignature`-only parts), so extraction joins all `.text` parts — the
runner does this.

Models: `gemini-3.1-pro-preview` (default; the 3.x pro tier is preview-only —
bare `gemini-3.1-pro` does not exist), `gemini-2.5-pro` (GA/stable, 1M ctx),
`gemini-3.5-flash` (fast). Do NOT use the `gemini` CLI — its OAuth route hits
persistent 429 capacity errors; the REST API with `GEMINI_API_KEY` works.
