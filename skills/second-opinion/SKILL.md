---
name: second-opinion
description: Get a second opinion from Kimi, Gemini, OpenAI, DeepSeek, xAI, GLM (z.AI), or MiniMax via API. Use when you want feedback on code, plans, documents, arguments, or any work product. Also useful when stuck debugging or wanting a different perspective.
argument-hint: [question or topic]
allowed-tools: Bash, Read, Glob, Grep
context: fork
model: sonnet
---

# Second Opinion Skill

Request feedback from another model to catch blind spots or get unstuck. Claude
remains the decision-maker — external input is one data point, not authoritative.

`model: sonnet` is deliberate: this fork only does plumbing (read files, fill a
`jq` template, run a script, parse an envelope), and without it the fork inherits
an Opus/Fable session's model and bills accordingly. The *review* comes from the
backend you route to, not from this fork. Keep the line.

## Additional resources

- User-facing usage guide and model details: [README.md](README.md)
- Endpoints, request shapes, model tables, timing evidence: [api-reference.md](api-reference.md)

## Available Backends

| Backend | Requires | Default model | Alternatives |
|---------|----------|---------------|--------------|
| Kimi | `MOONSHOT_API_KEY` | `kimi-k3` | (single tier; 1M ctx, always-on reasoning) |
| Gemini | `GEMINI_API_KEY` | `gemini-3.1-pro-preview` | `gemini-3.5-flash` (fast), `gemini-2.5-pro` (GA/stable, 1M ctx) |
| OpenAI | `OPENAI_API_KEY` | `gpt-5.6-sol` | `gpt-5.6-terra` (balanced), `gpt-5.5` (prior flagship). `gpt-5.6-luna` is tier-gated on some keys ([api-reference.md](api-reference.md)) |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-v4-pro` | `deepseek-v4-flash` (cheapest useful review); both 1M ctx |
| xAI | `XAI_API_KEY` | `grok-4.5` | `grok-4.3` (1M ctx, half price — long documents) |
| z.AI | `ZAI_API_KEY` | `glm-5.2` | glm-5.x line moves fast — newest on `GET /api/paas/v4/models` wins |
| MiniMax | `MINIMAX_API_KEY` | `MiniMax-M3` | `MiniMax-M2.7-highspeed` (faster tier) |

Each backend needs its API key exported in the environment (user setup — see
[README.md](README.md)). Table verified 2026-07; models move faster than skill
releases, so honor per-provider overrides: if `SECOND_OPINION_<PROVIDER>_MODEL`
is set (`SECOND_OPINION_KIMI_MODEL`, `..._GEMINI_...`, `..._OPENAI_...`,
`..._DEEPSEEK_...`, `..._XAI_...`, `..._ZAI_...`, `..._MINIMAX_...`), use its
value as that backend's default model instead of the table's. When an override is in play, always set
`reasoning_effort` explicitly — the runner's unset-effort gate knows only the
models listed here.

**Default:** Kimi `kimi-k3`. If `MOONSHOT_API_KEY` is unset, fall back to Gemini
and drop `reasoning_effort` (Gemini has no such parameter). Use another backend
when the user asks, when the default is unavailable, or for an additional
independent perspective — seven families means up to seven independent opinions.

**Always set `reasoning_effort` on `kimi-k3`.** Its server-side default is `max`,
so omitting it costs ~460 s versus ~90 s at `"low"` on the same prompt, for no
gain in review quality. Use `"low"` on the short path.

### Routing guidance

| Situation | Prefer |
|-----------|--------|
| General analytical review (default) | Kimi `kimi-k3` |
| Reasoning/debugging/edge cases | Kimi `kimi-k3`, or `gpt-5.6-sol` + `reasoning_effort: high` |
| File-heavy or long documents | Gemini `gemini-2.5-pro`, Kimi, or `grok-4.3` (1M ctx) |
| Fast/cheap feedback | `deepseek-v4-flash` or `gemini-3.5-flash` (Kimi is neither) |
| Another independent opinion | Any unused family — different family, different blind spots |
| No Kimi/OpenAI credits | Gemini (free tier) or DeepSeek (near-free) |

## When to Use

Use for `$ARGUMENTS`, or proactively for: code, plans, or documents worth
reviewing; implementation plans before committing to an approach; debugging when
stuck >2 attempts; academic writing critique; anything where another perspective
might surface overlooked issues.

## Execution model — read this first

This skill runs as a **fork**. Three facts shape everything:

1. A Bash tool call dies at 10 minutes. Long reviews cannot run synchronously here.
2. Background tasks started in a fork **die silently when it returns**. Never use
   `run_in_background` in this skill, for anything.
3. Foreground children **outlive the fork** — a killed fork orphans the runner,
   which keeps running and keeps billing. Hence `DEADLINE` and the PID file.

All calls go through `scripts/run-request.py` (stdlib Python, no deps). **The
runner enforces the gate itself**, refusing a long request with a `usage_error`
rather than letting a fork start it — but route correctly anyway:

- **Short path** — **both**: (a) request.json under 32 KB, **and** (b)
  `reasoning_effort` is `low`/`medium`, or unset on any backend except `kimi-k3`.
  Run synchronously in the fork:
  `MAX_TIME=420 DEADLINE=450 ATTEMPTS=1 python3 <skill-dir>/scripts/run-request.py <provider> $WORKDIR/request.json $WORKDIR/review [gemini-model]`
  with Bash tool timeout 540000 ms (above the 450 s `DEADLINE`, so an envelope
  always comes back before the tool gives up).
- **Long path** — 32 KB or larger, OR effort `high`/`xhigh`/`max`, OR `kimi-k3`
  with no effort set: **start nothing.** Prepare everything and hand back.

Exhaustive and mutually exclusive; (a) is required regardless of (b).

**Timeouts.** Responses stream, so `MAX_TIME` is a *socket* timeout, not a total
one — a stream that keeps arriving survives any duration, and `DEADLINE` is the
only real bound on total time. But `MAX_TIME` must still cover the **silent phase
before the first byte**, which can be huge: `gpt-5.6-sol` at `high` effort sent
nothing for over 10 minutes on a 52 KB input. So never shrink `MAX_TIME` to
"detect stalls" — that turns slow-but-working requests into hard failures. Leave
it at the 1800 default on the long path and bound the job with `DEADLINE`.

**The envelope.** The runner prints exactly one JSON object on stdout — parse it,
never guess:

| status | exit | meaning |
|---|---|---|
| `completed` | 0 | `model`, `usage`, `text_path`, `chars` |
| `partial` | 3 | same, plus `detail`; text on disk is real but stops early |
| `failed` | 1 | `error_class`, `http_status`, `log_path` |
| `usage_error` | 2 | bad argument, missing file, unset key, **or a gate refusal** |

A gate refusal ("long-path request refused") means you mis-routed — switch to the
long path, do not add `--long` to force it through. A `failed` envelope is always
a *finished* call, never a running one, but not always a dead end: deterministic
classes (`bad_request`, `not_found`, genuine `auth`, `timeout_budget`) are final,
while transient ones (`rate_limit`, `server_error`, `network`, `timeout`) went
unretried under `ATTEMPTS=1` and may succeed on another try. Say which you have.

## Workflow

1. Identify the target: what file, diff, or document to review.
   - If `$ARGUMENTS` names a file or topic, use that — for a fork this is
     normally the only input channel.
   - If the surrounding context makes the target unambiguous (e.g. user just
     wrote code), use that.
   - **If `$ARGUMENTS` is empty and nothing makes the target unambiguous, do NOT
     ask and do NOT guess — return `STATUS: FAILED — no target supplied`** (see
     the final-message contract). This skill always runs as a fork, so a
     clarifying question has no user to answer it and is an unrecoverable dead
     end; guessing a target (or defaulting to `git diff` / the newest-changed
     file) is worse still — reviewing the wrong thing, or redoing finished work,
     reads as success. A `FAILED` envelope is something the main session can
     detect and route around. (Empty `$ARGUMENTS` in a fork is an upstream
     delivery failure, not your logic — see README troubleshooting for the
     direct-runner fallback.)
   - Read the target and inline its content; no backend reads local files.
2. Choose backend and model (tables above).
3. `WORKDIR=<session scratchpad>/second-opinion-<slug>` (`mkdir -p`).
4. Build `$WORKDIR/request.json` with the temp-file + `jq --rawfile` pattern
   ([api-reference.md](api-reference.md)).
5. Apply the gate. Short path: run it, parse the envelope, return COMPLETED or
   PARTIAL. Long path: return NOT-RUN, start nothing.
6. **Do not evaluate or summarize the review** — hand back its path. The main
   session reads the file and judges it.

## Final-message contract (mandatory)

The fork's final message is the ONLY thing that survives it. Use one of these
templates. "Running", "waiting", and "monitoring" are banned — a fork cannot
truthfully say them about any process.

    STATUS: COMPLETED
    model: <actual model id>
    response: <the envelope's text_path>
    MAIN SESSION: Read that file — it is the deliverable and is not reproduced here.
    contents: <the review's own headings, quoted verbatim, plus its size.
     EXTRACTION, NOT CHARACTERIZATION — copy the reviewer's words; do not
     paraphrase, rank, or judge.>

    STATUS: PARTIAL (<chars> chars, cut short: <detail>)
    model: <actual model id>
    response: <the envelope's text_path>
    MAIN SESSION: Read that file. Completed findings are valid; the last one may
      stop mid-sentence — ignore that one.
    contents: <same rule as COMPLETED>

    STATUS: FAILED
    model: <model id>, error_class: <class>, http_status: <status or none>
    log: <the envelope's log_path>
    <deterministic or transient (see the envelope table), and what you tried. If
     you switched backends and one worked, report COMPLETED naming that backend.>

    STATUS: FAILED — no target supplied
    No `$ARGUMENTS` reached this fork and nothing in context identified something
    to review. Nothing was sent to any backend.
    MAIN SESSION: re-invoke with the target in `args`. If a forked invocation
      keeps arriving empty, skip the fork and drive scripts/run-request.py
      yourself (README troubleshooting).

    STATUS: NOT-RUN (long review — must be executed by the main session)
    request: <WORKDIR>/request.json (<size>, model <model>, reasoning_effort <value>)
    Main session: run this with run_in_background: true —
      DEADLINE=5400 ATTEMPTS=1 python3 <skill-dir>/scripts/run-request.py --long <provider> <WORKDIR>/request.json <WORKDIR>/review [gemini-model]
    On the completion notification, parse the envelope and read its text_path.
    If cancelled, kill the orphan: kill "$(cat <WORKDIR>/review-pid.txt)"

`--long` is required on the long path — without it the runner refuses to start.

**Relay the path, never the content.** The review is already on disk; copying it
through this message can only lose fidelity, and a summary drops the specific
cited objection that makes a second opinion worth having. Quoted headings carry
no judgment and do not anchor the reader; a characterization would.

**Never substitute your own review.** If every backend fails, report FAILED.
Whether to proceed without an outside opinion is the main session's decision.

## Using a partial review

A `partial` is genuine output that stops early — normally N complete findings
plus one cut mid-sentence. **Use it rather than discarding it.**

- **Never act on the truncated final item.** A halted sentence can reverse itself
  in the half you did not get ("a race condition — *unless* the caller holds the lock").
- **Never present a partial as complete.**
- **Enough?** If the completed findings are self-contained and give you concrete
  changes, act and move on.
- **More expected?** (It announced eight problems and you have three, or it was
  cut inside the central argument.) Act on what you have **first**, then re-run —
  the next review then sees the corrected state instead of repeating findings you
  have already fixed. Re-running immediately just pays twice for the same N.
- Truncating repeatedly at the same place means the target is too big: split it.

## Prompt Construction

Always include: the specific question; the relevant file content inlined; and
what kind of feedback you want.

    I'm working on [TASK]. My current approach is [APPROACH].
    Files to review: [INLINE CONTENT]
    Questions:
    1. What problems do you see with this approach?
    2. What edge cases might I be missing?
    3. Is there a simpler solution I'm overlooking?

Context budgets: Kimi, Gemini, DeepSeek, and `grok-4.3` handle ~1M tokens.
OpenAI and `grok-4.5` (500k) are smaller — for very large content prefer a
1M-context model or include only the relevant sections. z.AI and MiniMax
context windows are unverified here — check provider docs before sending
anything huge.

## Evaluating Feedback

**For the main session, after reading the file — not for the fork.** Judging a
review needs the surrounding context only the main session has.

**Take seriously:** specific technical errors with explanations; edge cases you
had not considered; alternative approaches with clear tradeoffs; structural
problems in arguments.

**Be skeptical of:** vague concerns without specifics; style preferences
presented as errors; suggestions ignoring stated constraints; "best practices"
without context.

**Discard:** feedback that misunderstands the problem; contradictions of verified
facts; generic advice not specific to the situation.

## Error Handling

**If the Bash call was cancelled or timed out instead of returning an envelope,
the runner is probably still alive** — foreground children outlive the fork, and
it keeps billing with nobody reading the result. Kill it *before* any retry, or
you end up paying for two generations at once:

    kill "$(cat $WORKDIR/review-pid.txt)"

On a non-completed envelope:

1. Note it briefly: "Couldn't get [backend]'s input — [`error_class`: `detail`]" (with `log_path`).
2. Try another backend — **but check the clock first.** The fork's whole budget
   is one Bash call, and two full-deadline attempts overrun it. Retry in-fork
   only if the first failure was **fast** (under ~60 s). Otherwise report FAILED
   and let the main session re-route.
3. Do not retry a deterministic class — it is pointless by definition.
   `timeout_budget` specifically means the request needs a larger `MAX_TIME`, not
   another attempt.

Key checks: `[ -n "$MOONSHOT_API_KEY" ]`, `[ -n "$GEMINI_API_KEY" ]`,
`[ -n "$OPENAI_API_KEY" ]`, `[ -n "$DEEPSEEK_API_KEY" ]`, `[ -n "$XAI_API_KEY" ]`,
`[ -n "$ZAI_API_KEY" ]`, `[ -n "$MINIMAX_API_KEY" ]`.
A `usage_error` of "`<KEY>` not set" means that backend's key is absent.
