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
per-provider defaults (`scripts/run-request.py`; every default verified
2026-09-25, `grok-4.3` 2026-09-26, against the provider's `GET /models` and a
live completion). Only `--prompt-file` runs resolve this way; legacy mode
never reads the env var.

`--effort` takes `low`, `medium`, `high`, `xhigh`, or `max`, case-insensitive,
lowercased into the body before it is sent. Per-provider tier validity is
**not** validated here — e.g. `kimi-k3` rejecting `"medium"` (see its quirks
below) surfaces as the provider's own 400, classified `bad_request`, rather
than as a decay-prone table baked into the runner.

**Omitting `--effort` means `DEFAULT_EFFORT`, which is `"high"`.** Every
provider that has the parameter gets the same level, so a review's depth is a
property of the skill rather than of whichever vendor default it happened to
land on. `high` is the highest level every backend accepts: `kimi-k3` and
`glm-5.3` have no `"medium"`, which rules out the middle, and `xhigh`/`max`
are not offered everywhere. Pass `--effort low` for a quick check.

This injection is **provider-keyed, not model-keyed** — including for a model
reached through `SECOND_OPINION_<PROVIDER>_MODEL`. It is a *policy* ("ask every
backend for the same level"), not the *protection* it used to be ("force `low`
so a model that secretly reasons at max cannot run away"). A protection needed
to know the model's own default and so had to skip unknown ids; a policy does
not. If an overridden model has no `reasoning_effort`, the provider may say so
with a 400 (`bad_request`), or it may accept the field and ignore it:
`kimi-k2.7-code` returned 200 at every level, `medium` included, although
Moonshot documents the parameter as K3-only (verified 2026-09-25).

**The default is deliberately gate-blocking.** `high` is one of the gate's
refusal conditions, so a build-mode call that passes no `--effort` is refused
in the foreground unless it passes `--long` — because it genuinely is a
long-path request. The sanctioned flow always passes `--long`; a direct caller
who wants a foreground run passes `--effort low`.

`--effort` on gemini is a usage_error, and nothing is injected for it either —
gemini has no such API parameter.

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
bound the run with `DEADLINE`. (One later run, 2026-09-25: `gpt-6-sol`
finished a 121 KB branch-diff review at `high` in 110 s end to end. One run does not
retire the worst case.)

**An interrupted run leaves a usable review.** Text already received is on disk.
The runner then emits `{"status":"partial", …, "chars":N, "detail":"…"}` with
exit code **3**. That is not a failure — it is real model output that stops
early. Guidance on acting on one lives in the root README.

**A run the provider itself cut short is reported the same way.** The runner
sends no `max_tokens`, so a backend's server-side output cap can end a review
mid-sentence while the HTTP call succeeds — which used to land as a short but
truthful-looking `completed`. The provider says so in its finish reason, and
the runner reads it: `choices[0].finish_reason` on the OpenAI-compatible
backends, `candidates[0].finishReason` on gemini, at the choice/candidate level
in streaming too rather than inside the delta. Whatever it reports is recorded
in the envelope as `finish_reason`, lowercased. Only a **cap** reason —
`length`, or gemini's `MAX_TOKENS` — downgrades the run to `partial`; anything
else (`content_filter` and friends) stays `completed` with the reason visible,
because `partial` instructs the reader to discard the last finding and a false
`partial` therefore destroys real work.

Verified 2026-08-20. Wire shape: z.AI `glm-5.3` (`"length"`) and
`gemini-3.1-pro-preview` (`"MAX_TOKENS"`), both delivered in the same SSE event
as the usage totals. End to end through the runner: `kimi-k3` capped at 300
tokens returned `partial`, exit 3, `finish_reason: "length"`, with 1320
characters of real review on disk cut mid-sentence — the same run would have
reported `completed` before 0.2.3. The cap reason is unprobed on the
other four backends; a reason a provider never sends is reported as absent,
never as a clean stop.

**A stream that closes without an end marker is `partial` too.** A clean end
carries a marker: the `[DONE]` sentinel or a finish reason. If text arrived
and the connection then closed quietly with neither, nothing says the provider
finished, so the runner reports `partial`, its `detail` naming the missing
marker. With no text at all the run is `empty` as before, or `output_cap`
when a cap reason explains it. The converse holds too: the finish reason
arrives with the last text or after it, so a stream that breaks after one
lost only the usage totals and is not reported as cut (a cap reason still
makes it `partial`). Probed 2026-09-26, each default model on a short prompt:
all seven backends sent a finish reason on a clean end, five of them also
`[DONE]`; minimax and gemini sent no `[DONE]`, so for them the finish reason
is the only marker.

Wire details, if debugging: OpenAI-compatible backends take `stream: true` in
the body (the runner injects it, along with `stream_options.include_usage` so
the final event carries token counts) and emit `choices[0].delta.content`,
terminated by `data: [DONE]`, except minimax, which closed after its usage
event in the 2026-09-26 probe. That trailing usage event carries `choices: []`, so the finish reason
arrives one event earlier. Gemini instead needs a different verb and query
param — `:streamGenerateContent?alt=sse` (the runner rewrites the URL) — and
emits `candidates[0].content.parts[].text` with no
`[DONE]` sentinel. The runner reads candidate 0 only, streaming or not.

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
| `completed` | 0 | `provider`, `model`, `http_status`, `attempts`, `usage`, `text_path`, `chars`, `log_path`, and `finish_reason` when the provider reported one |
| `partial` | 3 | same, plus `detail` — real text on disk, cut short: the stream broke or closed without an end marker, or `finish_reason` says the output hit the model's token cap |
| `failed` | 1 | `provider`, `model`, `error_class`, `http_status`, `attempts`, `detail`, `raw_path`, `log_path` |
| `usage_error` | 2 | `detail` — bad argument, missing file, unset key, **or a gate refusal**; no request was attempted |

**The gate.** A foreground tool call dies at 10 minutes and orphans the
runner (it keeps running, and billing) if the request turns out to be too big
or too slow, so the runner refuses to start one as a `usage_error` prefixed
`long-path request refused: ` — unless `--long` says the caller knows it is
running in the background. Blocking conditions (any one is enough):

- the serialized request body is >= 32768 bytes;
- `reasoning_effort` is `high`, `xhigh`, or `max`;
- the resolved model is in `HIGH_EFFORT_BY_DEFAULT` (`kimi-k3`,
  `deepseek-v4-pro`, `deepseek-flash`, `grok-4.7`) and no `reasoning_effort`
  was set — those models reason at `high` or above when the field is absent
  (`kimi-k3` at `max`, the others at `high`), which makes the request
  wire-identical to the condition above. Only reachable in legacy mode: build
  mode always resolves an effort.

Because `DEFAULT_EFFORT` is `high`, the second condition fires on **every**
build-mode call that passes no `--effort`. That is the design, not an
oversight — the default is a long-path request and the gate says so. `--long`
or `--effort low` is the answer, depending on which the caller meant.

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
`client_error`, `timeout_budget`, `output_cap`, `internal`.
Transient — retried up to `ATTEMPTS` times: `rate_limit`, `server_error`,
`network`, `timeout`, `empty`, `bad_response`.

`empty` = HTTP 200 with no extractable text. `bad_response` = a non-JSON body.
`timeout_budget` = the full `MAX_TIME` elapsed without a single byte, which means
the budget is too small rather than the call being unlucky — raise `MAX_TIME`
instead of retrying. `output_cap` = an empty 200 whose `finish_reason` says the
model reached its output-token cap: reasoning runs first, so a small enough cap
is spent entirely on thinking and no review is ever produced. Deterministic for
the same reason `timeout_budget` is — the retry sends the identical request and
burns the identical budget. Measured 2026-08-20: `glm-5.3` capped at 1500 tokens
returned zero content at caps of both 1500 and 4000 tokens, four consecutive
attempts each before this class existed. Lower the reasoning effort, shorten the
prompt, or route elsewhere. `internal` = an unexpected exception in
the runner itself; the envelope still arrives so the caller never sees a bare
traceback.

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
a value (see "Model and effort resolution" above) — `DEFAULT_EFFORT` (`high`)
on every OpenAI-compatible backend unless `--effort` says otherwise.

Gemini's shape has no `"model"` field — see "Gemini backend" below for why:

    {
      "systemInstruction": {"parts": [{"text": "<system string above>"}]},
      "contents": [{"parts": [{"text": "<prompt file content>"}]}]
    }

The runner does not add `temperature`, `top_p`, `n`, `presence_penalty`, or
`frequency_penalty` to either shape — Kimi fixes them server-side and the
other backends do not need them here.

### Models

Verified 2026-09-25 (`grok-4.3`: 2026-09-26) — each id listed by the
provider's `GET /models` and answered a live completion through the runner at
the shared `high`. Prices live in the skill README's model table; measured
per-review costs in the root README's Cost section. To change a backend's default without
editing the skill, set `SECOND_OPINION_<PROVIDER>_MODEL` (see SKILL.md
"Available Backends"). Gemini's models are in "Gemini backend" below.

| Provider | Model | Role |
|---|---|---|
| Kimi | `kimi-k3` | flagship (**default**); 1M ctx; always-on reasoning |
| OpenAI | `gpt-6-luna` | cheap tier (**default**); 1.05M ctx (its predecessor `gpt-5.6-luna` was tier-gated on some keys — see the flaky-401 section) |
| OpenAI | `gpt-6-sol` | flagship; the in-depth pick; 1.05M ctx |
| DeepSeek | `deepseek-flash` | **default** (DeepSeek-V4.1-Flash); 1M ctx |
| xAI | `grok-4.3` | **default**; 1M ctx |
| xAI | `grok-4.7` | newer, dearer; 500k ctx |
| z.AI | `glm-5.3` | **default**; 1M ctx |
| z.AI | `glm-5.3-flash` | cheap tier; 1M ctx |
| MiniMax | `MiniMax-M3` | **default**; 1M ctx; `<think>` quirk below |

Naming traps (verified 2026-09-25 unless dated):

- Kimi K3 has only the one id `kimi-k3`; do not send the K2.x `thinking`
  parameter. `kimi-k2.7-code` is not a cheaper K3 for reviews: it has no
  `reasoning_effort` (it accepts the field and ignores it), and on a 121 KB
  branch diff it hit its output-token cap before any review text arrived
  (`output_cap`).
- GPT-6 has `-sol`, `-luna` and `-astra`; there is no `gpt-6-terra` and no
  bare `gpt-6`. `gpt-5.6-sol` is still listed, at twice `gpt-6-sol`'s price.
- DeepSeek retired `deepseek-v4-flash` on 2026-09-10. The id still answers,
  but `deepseek-flash` serves it — the response's `model` field says so. The
  older `deepseek-chat`/`deepseek-reasoner` aliases likewise resolve to the
  flash tier (verified 2026-08-22). Always name a current id.
- `glm-5.3-prime` appears on aggregator listings but not on the z.AI endpoint:
  a completion returns 400, "Unknown Model".
- Ignore xAI's `grok-4.20-*`, `grok-build-*` and `grok-imagine-*` entries.
  `grok-4.5` and `grok-4.6` are still listed, at `grok-4.7`'s price.
- For z.AI and MiniMax, `GET /models` on the endpoint host lists the
  candidates for *your* key — but **a listing is not access**, so before
  promoting a newer id, run one live completion on it. `glm-5.3` was listed on
  2026-08-16 while every completion on a standard API key failed with error
  1220, "You do not have permission to access glm-5.3" (launch gating to the
  GLM Coding Plan); the gate had lifted by 2026-08-20.

### z.AI and MiniMax quirks (verified 2026-07-23, live smoke tests)

- Both stream fine through the runner (accept the injected `stream` +
  `stream_options`) and reason by default (usage shows `reasoning_tokens`) —
  re-confirmed for `glm-5.3` on 2026-08-20. Small-prompt wall clock: `glm-5.3`
  ~15 s (2026-08-20), `MiniMax-M3` ~5 s.
- **MiniMax puts its chain of thought INSIDE `message.content`, wrapped in
  `<think>...</think>`** — not in the `reasoning_content` field other backends
  use. The runner strips those blocks for `provider == "minimax"` (tags can
  span SSE chunks, so it strips after the join and rewrites `-text.md`). A
  stream cut *inside* a think block therefore yields empty text, classified
  `empty`, not `partial` — correct, since no review had arrived yet. If the
  emptiness comes from the token cap rather than a cut — thinking ran to the
  cap and the review never started — it is `output_cap` instead, and not
  retried.
- **Both accept `reasoning_effort`** (verified 2026-08-23; it was carried as
  unverified from 2026-07-23 until then). `glm-5.3` takes **`low`, `high`,
  `max` and nothing else** — `medium` and `xhigh` each come back as a
  synchronous 400, error code 1210, *"This model always engages in thinking and
  cannot be disabled; please use low, high, or max"*, which names the valid set
  outright. Validation runs ahead of the rate limiter, so the invalid levels
  400 on the same key where the valid ones were being 429'd. `MiniMax-M3`
  returns 200 for every level including `medium` and `xhigh`, so it is
  permissive; whether it acts on the value is **not** established — one probe
  gave 28 reasoning tokens at `low`, 430 at `medium` and 52 at `high`, which
  ranks nothing. Sending the shared default is harmless there and keeps the
  request shape uniform. `glm-5.3-flash` and `glm-5.3-flashx` take the same
  three levels as `glm-5.3`: `medium` returns the same 1210 (verified
  2026-09-25).
- z.AI's own unset default is not wire-verified (the unset probe was
  rate-limited). z.AI's docs say it is `max`, but a doc claim is not positive
  evidence, so `glm-5.3` is **not** in `HIGH_EFFORT_BY_DEFAULT`. It costs
  nothing in build mode, which always resolves an effort; it means only that a
  hand-built z.AI body with the field absent is not gate-refused.

### Kimi `kimi-k3` quirks

- **1M-token context** (1,048,576). `max_completion_tokens` defaults to 131072,
  settable up to 1048576.
- **Thinking is always on, and defaults to the *slowest* setting.**
  `reasoning_effort` accepts `"low"`, `"high"`, and `"max"` — there is no
  `"medium"` — and **the server default is `"max"`**. (Verified 2026-07-20 from
  `GET https://api.moonshot.ai/v1/models`, whose `kimi-k3` entry reports
  `reasoning_efforts: {valid_efforts: ["low","high","max"], default_effort: "max"}`;
  unchanged on 2026-09-25.) Do not send the K2.x `thinking` parameter.
- **Always set `reasoning_effort` explicitly.** Omitting it is *not* neutral —
  it silently buys a max-effort call. Measured on one identical 10.8 KB review
  prompt (2026-07-20):

  | `reasoning_effort` | wall clock | reasoning tokens |
  |---|---|---|
  | unset (= `max`) | **462 s** | 11,595 |
  | `"low"` | **92 s** | 919 |

  Both reviews led with the same top finding, so max effort bought latency,
  not insight. Build mode never leaves the field unset: it sends the shared
  `high` unless `--effort` says otherwise (see "Model and effort resolution"
  above). This measurement is what the gate
  protects everyone else against — a legacy request.json (or any hand-built
  body) for `kimi-k3` with no `reasoning_effort` field trips the gate's
  unset-effort condition and is refused as a foreground call (see "Envelope,
  gate, and orphan cleanup" above).
- **Fixed sampling params:** `temperature=1.0`, `top_p=0.95`, `n=1`,
  `presence_penalty=0`, `frequency_penalty=0` are fixed server-side — omit them
  from the request (the standard request shape above already does).
- **Cost:** the highest per-token price of the runner's defaults, and always reasoning, so
  slower and dearer than the flash tiers (prices: the skill README's model
  table). Route quick or cheap checks elsewhere.

### `reasoning_effort`

Every backend but Gemini takes `"reasoning_effort"`, and the runner sends the
same `DEFAULT_EFFORT` (`high`) to all of them unless `--effort` says otherwise
(see "Model and effort resolution" above). Accepted levels, which are **not**
uniform:

| Backend | Accepted levels | Verified |
|---|---|---|
| Kimi `kimi-k3` | `low`, `high`, `max` — no `medium`; always reasons regardless | 2026-09-25, `GET /v1/models` |
| OpenAI `gpt-6-sol`, `gpt-6-luna` | `none`, `low`, `medium`, `high`, `xhigh` — no `max` | 2026-09-25, the 400 names the set |
| DeepSeek `deepseek-flash`, `deepseek-v4-pro` | `low`, `high`, `max` per `/models`; `medium` and `xhigh` also return 200 and carry `high`'s prompt overhead on `deepseek-v4-pro` | 2026-09-25 |
| z.AI `glm-5.3`, `-flash`, `-flashx` | `low`, `high`, `max` — no `medium`, no `xhigh` | 2026-08-23 and 2026-09-25, error 1210 names the set |
| MiniMax `MiniMax-M3` | every level returns 200; effect unestablished | 2026-08-23 |
| xAI `grok-4.3` | `none`, `low`, `medium`, `high`, `xhigh` | 2026-09-25, `GET /v1/models`; `high` ran through the runner 2026-09-26 |
| xAI `grok-4.7` | `low`, `medium`, `high`, `xhigh` — no `none`, no `max` | 2026-09-25, `GET /v1/models` and the 400 |
| Gemini | none — no such parameter, and `--effort` is a usage_error | 2026-07 |

`low` and `high` are the levels every backend accepts; `high`, the higher,
is the shared default. `none` exists at the API on some models, but `--effort`
does not offer it. Per-provider
validity is still not checked in code: an unaccepted level surfaces as the
provider's own 400, classified `bad_request`.

**Where the vendor defaults sit** — which is what a *legacy* body with the
field absent gets, since build mode always resolves an effort. They differ
enough to be the reason a shared default exists at all: OpenAI's docs give
`medium` for `gpt-6-sol` (not wire-verified), and `gpt-6-luna`'s is
unverified (OpenAI's `/models` reports no effort metadata); DeepSeek's is
`high` (measured below); **`kimi-k3` defaults to `max`** server-side; z.AI's
docs say `max` (not wire-verified); xAI's `/models` gives `low` for
`grok-4.3` and `high` for `grok-4.7`; MiniMax's is unknown. So hand-build a body and you inherit
whatever the vendor chose — always set `reasoning_effort` explicitly there.

**DeepSeek, measured 2026-09-25.** DeepSeek has documented three levels —
`low`, `high`, `max` — since 2026-08-13, and `GET /models` now reports them per
model with `default_level: "high"`. The API is more permissive than the
listing: `medium` and `xhigh` also return 200 on both models. On
`deepseek-v4-pro` the levels still show on the wire as a fixed server-side
prompt injection. On one one-line prompt, `low` billed 11 prompt tokens;
`medium`, `high`, `xhigh` and an omitted field billed 90; `max` billed 103. So
an omitted field is `high`, `medium` and `xhigh` look like `high` on the
wire, and `max` is a separate tier above it. `deepseek-flash` bills the same prompt
tokens at every level, so the wire gives no fingerprint there; its `/models`
entry is the evidence. Both models are in `HIGH_EFFORT_BY_DEFAULT` on this
basis, which makes the gate refuse an unset-effort hand-built body for them
exactly as for `kimi-k3`.

Reasoning volume does not rank the tiers: on `deepseek-v4-pro` (2026-08-22),
`low` spanned 530–1,239 reasoning tokens across three runs and `high` spanned
835–2,792. Don't read a single run's token count as evidence that a level
"took".

Note the cost the shared default carries: `high` on a large input routinely
runs 5–30 minutes, which is why `high`/`xhigh`/`max` is one of the gate's
blocking conditions (see "Envelope, gate, and orphan cleanup" above) and why
the default therefore blocks. Drop to `low` for a quick check or a foreground
run; go above `high`, where the backend offers it, only for genuinely hard
problems.

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

Model (verified 2026-09-25): `gemini-3.8-flash` (default; 1M ctx; free
tier). It thinks by default: a 2026-09-25 run with no thinking control sent
spent 27k thought tokens. The runner sends Gemini no thinking control, so
the model thinks at its own default; Google
documents `medium` for `gemini-3.8-flash` (not wire-verified). Avoid the `gemini-pro-latest` and
`gemini-flash-latest` aliases: they move, so nothing can be verified against
them. Do NOT use the `gemini` CLI — its OAuth route hits persistent 429
capacity errors; the REST API with `GEMINI_API_KEY` works.
