# API Reference (Kimi, OpenAI, DeepSeek, xAI, Gemini)

All backends are called through the shipped runner (stdlib Python, no deps):

    python3 scripts/run-request.py [--long] <provider> <request.json> <output-base> [gemini-model]

- `provider`: `kimi` | `openai` | `deepseek` | `xai` | `gemini`
- Writes `<output-base>-raw.json`, `-text.md`, `-log.txt`, and `-pid.txt`.
- `--long`: assert this is a long-path run (main session, background). Required
  for anything the gate blocks — see below.

Env vars:

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

Short path (synchronous, in-fork): `MAX_TIME=420 DEADLINE=450 ATTEMPTS=1`.
One attempt, because a retry cannot fit in the fork's budget anyway.
Long path (main session, background): `--long DEADLINE=5400 ATTEMPTS=1`, leaving
`MAX_TIME` at its 1800 default.

**Do not shrink `MAX_TIME` to "detect stalls".** It looks like an idle timeout
once streaming is on, but it also governs the silent wait before the first byte,
and that wait can be enormous (measured below). A small value converts a
slow-but-working request into a hard failure. `DEADLINE` is the correct bound.
Learned the hard way: `MAX_TIME=300` on a 52 KB `gpt-5.6-sol` review produced
four identical 300 s timeouts and ~20 wasted minutes. The runner now classifies
that case as `timeout_budget` and refuses to retry it.

Retries: `ATTEMPT*15`-second backoff (429 honors a capped `Retry-After`).

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
early. Guidance on acting on it: SKILL.md § "Using a partial review".

Wire details, if debugging: OpenAI-compatible backends take `stream: true` in
the body (the runner injects it, along with `stream_options.include_usage` so
the final event carries token counts) and emit `choices[0].delta.content`,
terminated by `data: [DONE]`. Gemini instead needs a different verb and query
param — `:streamGenerateContent?alt=sse` (the runner rewrites the URL) — and
emits `candidates[0].content.parts[].text` with no `[DONE]` sentinel.

API keys (each must be exported in the environment; the runner refuses with a
`usage_error` naming the missing var): `MOONSHOT_API_KEY`, `OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`, `XAI_API_KEY`, `GEMINI_API_KEY`.

**Owned by SKILL.md, not repeated here** (one home per fact, so the two cannot
drift apart): the gate's blocking conditions, the envelope's statuses and exit
codes, and how to kill an orphaned runner via `<output-base>-pid.txt`. This file
covers provider specifics only — endpoints, request shapes, models, and measured
behaviour.

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

## OpenAI-compatible backends (Kimi, OpenAI, DeepSeek, xAI)

Endpoints (the runner knows these; listed for debugging):

| Provider | Endpoint |
|---|---|
| Kimi | `https://api.moonshot.ai/v1/chat/completions` |
| OpenAI | `https://api.openai.com/v1/chat/completions` |
| DeepSeek | `https://api.deepseek.com/chat/completions` |
| xAI | `https://api.x.ai/v1/chat/completions` |

Auth is `Authorization: Bearer $<KEY>`. Response text lives at
`.choices[0].message.content`. All current default models are native reasoning
models (usage shows `reasoning_tokens`).

### Building a request

Always use the temp-file + `jq --rawfile` pattern — nested command
substitutions corrupt escaping for prompts with quotes/`$`/backticks:

    TMPFILE=$(mktemp)
    trap 'rm -f "$TMPFILE"' EXIT
    cat > "$TMPFILE" << 'PROMPT_EOF'
    YOUR_PROMPT_HERE (inline file content — no backend reads local files)
    PROMPT_EOF
    jq -n --rawfile prompt "$TMPFILE" '{
      model: "kimi-k3",
      reasoning_effort: "low",
      messages: [
        {role: "system", content: "You are an expert reviewer providing a second opinion. Be specific, cite evidence, and explain your reasoning."},
        {role: "user", content: $prompt}
      ]
    }' > request.json
    rm -f "$TMPFILE"

The default backend is Kimi (`model: "kimi-k3"`); swap the model string for
another OpenAI-compatible backend as needed. Do NOT add `temperature`, `top_p`,
`n`, `presence_penalty`, or `frequency_penalty` — Kimi fixes them server-side
and the other backends do not need them here.

`reasoning_effort: "low"` is not optional boilerplate on `kimi-k3`: omitting it
means max effort (~5× the latency) and the runner's gate will refuse the run.
Drop the field for the other backends, which default to a sane middle tier.

Use `<< PROMPT_EOF` (unquoted) instead when the heredoc must expand a shell
variable such as `$(cat file)` output or `$DIFF`.

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

Naming traps (verified): Kimi K3 has only the one id `kimi-k3` (do not use the
K2.x `thinking` parameter); there is no bare `gpt-5.6` (only `-sol`/`-terra`/`-luna`);
`gpt-5.5-pro` is Responses-API-only and not wired in; DeepSeek's old
`deepseek-chat`/`deepseek-reasoner` aliases are deprecated as of 2026-07-24 —
use the `deepseek-v4-*` names; ignore xAI's `grok-4.20-*`, `grok-build-*`, and
`grok-imagine-*` entries.

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

  Both reviews led with the same top finding, so max effort bought latency, not
  insight. 462 s also sits only 18 s inside the short path's 480 s per-attempt
  budget — which is exactly how "Kimi always times out" happened. Use `"low"`
  for the short path; reserve `"high"`/`"max"` for the long path. The runner
  enforces this (see "The gate" below).
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
tier, so omitting the field is safe there. **`kimi-k3` defaults to `max`**, so
omitting it there is a max-effort call — always set it explicitly on Kimi.

Raise effort for debugging, edge-case analysis, and hard problems, and note that
a high-effort setting on a large input routinely runs 5–30 minutes. That is why
the runner's gate refuses any `high`/`xhigh`/`max` request without `--long`,
routing it through the main session in background (see SKILL.md "Execution
model").

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
— the model goes in the URL, so the runner takes it as the 4th argument (and the
request body has no model field). The key travels in the `x-goog-api-key`
header, not the URL, so it stays out of `ps`/logs:

    jq -n --rawfile prompt "$TMPFILE" '{
      systemInstruction: {parts: [{text: "You are an expert reviewer providing a second opinion. Be specific, cite evidence, and explain your reasoning."}]},
      contents: [{parts: [{text: $prompt}]}]
    }' > request.json

Response text can span multiple `parts` (thinking models emit
`thoughtSignature`-only parts), so extraction joins all `.text` parts — the
runner does this.

Models: `gemini-3.1-pro-preview` (default; the 3.x pro tier is preview-only —
bare `gemini-3.1-pro` does not exist), `gemini-2.5-pro` (GA/stable, 1M ctx),
`gemini-3.5-flash` (fast). Do NOT use the `gemini` CLI — its OAuth route hits
persistent 429 capacity errors; the REST API with `GEMINI_API_KEY` works.
