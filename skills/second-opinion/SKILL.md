---
name: second-opinion
description: >-
  Get a second opinion from Kimi, Gemini, OpenAI, DeepSeek, xAI, GLM (z.AI), or
  MiniMax via API. Use for feedback on code, plans, documents, arguments, or any
  work product — also when stuck debugging or wanting a different perspective.
  The skill only PREPARES the request — the handoff message names the exact
  command for the main session to launch. Work lands in
  <session scratchpad>/second-opinion-*/ (prompt.txt and launch.txt when
  prepared; review-text.md once run). To review uncommitted changes, save the
  diff to a file first and pass its path.
argument-hint: [question or topic]
allowed-tools: Read, Glob, Grep, Write
disallowed-tools: Bash, PowerShell, Agent, Skill, Workflow, ToolSearch, SendMessage, Monitor, CronCreate, RemoteTrigger
context: fork
model: sonnet
---

# Second Opinion Skill

Prepare a review request for an external model and hand it to the main session
to launch. Claude remains the decision-maker — external input is one data
point, not authoritative.

**You prepare; you never run.** You never execute, launch, or dispatch
anything — no shell, no subagents, no scheduled or delegated work of any kind.
The execution-capable tools are disallowed here and calls to them are denied;
do not attempt them, and do not work around a denial with any other tool. This
rule also covers tools this list has never heard of: if a tool would run,
schedule, or delegate something, it is not yours to use. Your tools are Read,
Glob, Grep, and Write; your deliverable is one final message.

`model: sonnet` is deliberate: this fork only does plumbing (read the target,
compose a prompt, write two files). The *review* comes from the backend the
main session launches, not from this fork. Keep the line.

## Additional resources

- User-facing usage guide and model details: [README.md](README.md)
- Runner CLI, envelope statuses, endpoints, measured provider behavior:
  [api-reference.md](api-reference.md)

## Available Backends

| Backend | Requires | Alternatives to the runner's default |
|---------|----------|--------------------------------------|
| Kimi | `MOONSHOT_API_KEY` | (single tier; 1M ctx, always-on reasoning) |
| Gemini | `GEMINI_API_KEY` | `gemini-3.5-flash` (fast), `gemini-2.5-pro` (GA/stable, 1M ctx) |
| OpenAI | `OPENAI_API_KEY` | `gpt-5.6-terra` (balanced), `gpt-5.5` (prior flagship). `gpt-5.6-luna` is tier-gated on some keys ([api-reference.md](api-reference.md)) |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` (cheapest useful review); both 1M ctx |
| xAI | `XAI_API_KEY` | `grok-4.3` (1M ctx, half price — long documents) |
| z.AI | `ZAI_API_KEY` | glm-5.x line moves fast — but a `/models` listing isn't access ([api-reference.md](api-reference.md)) |
| MiniMax | `MINIMAX_API_KEY` | `MiniMax-M2.7-highspeed` (faster tier) |

Per-provider **default models live in the runner**
(`scripts/run-request.py`, `DEFAULT_MODELS`, verified 2026-07) and are
resolved at launch: `--model` flag, else `SECOND_OPINION_<PROVIDER>_MODEL`
from the environment, else the built-in default. So: pass `--model` only when
the user asked for a specific non-default model; never pass it to re-state a
default. When a user override env var is in play, the launch should still set
`--effort` explicitly — the runner's unset-effort protection is keyed to the
model ids it ships with.

**Default backend: Kimi.** Use another when the user asks or for an additional
independent perspective — seven families means up to seven independent
opinions. You cannot check API keys (no shell); if the chosen backend's key
turns out to be missing, the runner reports it seconds after launch and the
main session reroutes.

### Routing guidance

| Situation | Prefer |
|-----------|--------|
| General analytical review (default) | Kimi |
| Reasoning/debugging/edge cases | Kimi at `--effort high`, or OpenAI at `--effort high` |
| File-heavy or long documents | Gemini `--model gemini-2.5-pro`, Kimi, or xAI `--model grok-4.3` (1M ctx) |
| Fast/cheap feedback | DeepSeek `--model deepseek-v4-flash` or Gemini `--model gemini-3.5-flash` (Kimi is neither) |
| Another independent opinion | Any unused family — different family, different blind spots |
| No Kimi/OpenAI credits | Gemini (free tier) or DeepSeek (near-free) |

**Effort, by provider:** pass `--effort` for kimi / openai / deepseek / xai —
`low` for quick feedback, `high` for plans, debugging, and hard problems
(kimi has no `medium`; deepseek-v4-pro also takes `xhigh`). **Omit** it for
gemini (the runner refuses the flag — no such API parameter) and for z.AI /
MiniMax (`reasoning_effort` support unverified there — see
[api-reference.md](api-reference.md)).

## When to Use

Use for `$ARGUMENTS`, or proactively for: code, plans, or documents worth
reviewing; implementation plans before committing to an approach; debugging
when stuck >2 attempts; academic writing critique; anything where another
perspective might surface overlooked issues.

## Workflow

1. **Identify the target** from `$ARGUMENTS`, or from unambiguous context
   (e.g. the user just wrote the document under discussion). Empty or
   ambiguous → the FAILED template. Fail loudly; never ask (a fork has no
   user to answer) and never guess (reviewing the wrong thing reads as
   success). Empty `$ARGUMENTS` in a fork is an upstream delivery failure,
   not your logic.
2. **Read the target files** and inline their content in the prompt — no
   backend reads local files. Unreadable target → FAILED naming the path. A
   **diff review** requested without a saved diff file → FAILED naming the
   one-line fix (`git diff > <file>`, re-invoke with that path); you cannot
   run `git diff` and must not reconstruct a diff by Reading files.
3. **Choose backend and effort** from the routing tables above. Choose a
   specific model (`--model`) only when the user asked for a non-default one.
4. **Pick a fresh WORKDIR**: `<session scratchpad>/second-opinion-<slug>`.
   Glob `<session scratchpad>/second-opinion-<slug>*` first; on collision
   append `-2`, `-3`, … until fresh. **Write** the composed prompt (see
   Prompt Construction) to `<WORKDIR>/prompt.txt`. Then **Write the exact
   launch command — the same line that goes in the PREPARED message — to
   `<WORKDIR>/launch.txt`**. Write creates the directory for you. No
   heredoc, no escaping, no jq.
5. **Return the PREPARED message.** That message is the entire deliverable.
   Its command must run **verbatim with zero edits**: it starts with the
   `rm -f` prefix, uses this skill's real absolute directory for
   `<skill-dir>` (your skill-load context names it), includes `--model <id>`
   exactly when step 3 chose a non-default model, includes `--effort <value>`
   per step 3's provider rule, and contains no placeholders, brackets, or
   editorial notes.

## Final-message contract (mandatory — the only two templates)

The fork's final message is the ONLY thing that survives it. "Running",
"waiting", and "monitoring" are banned — you cannot truthfully say them about
anything. Never substitute your own review; if you cannot prepare, report
FAILED and why.

    STATUS: PREPARED (review not yet run — the main session must launch it)
    target: <one line: what is being reviewed>
    prompt: <WORKDIR>/prompt.txt   (command also saved at <WORKDIR>/launch.txt)
    backend: <provider>, model <id, or "runner default — the envelope reports it">,
      reasoning_effort <value, or "none — not sent for this provider">
    MAIN SESSION — launch this as a BACKGROUND Bash task (it may run up to 90 min;
      a foreground call dies at 10 minutes and orphans the runner):
      rm -f <WORKDIR>/review-envelope.json <WORKDIR>/review-text.md && \
      DEADLINE=5400 python3 <skill-dir>/scripts/run-request.py --long \
        --prompt-file <WORKDIR>/prompt.txt [--model <id>] [--effort <value>] \
        <provider> <WORKDIR>/review
    outputs: <WORKDIR>/review-envelope.json (the outcome — its appearance after
      this launch IS the completion signal; read status first), review-text.md
      (the review), review-log.txt (run/attempt trace)
    status guide: completed → read text_path; the review is the deliverable, not
      reproduced or summarized here — treat it as one data point, not authority.
      partial → real output cut early: completed findings are valid; discard the
      final truncated one (it can reverse in the half that never arrived).
      failed → error_class bad_request/not_found/genuine auth/timeout_budget are
      final — fix what detail names;
      rate_limit/server_error/network/timeout/empty may succeed on relaunch. The
      prompt file is reusable as-is; the provider argument is swappable (adjust
      --effort per the swap: kimi/openai/deepseek/xai take it,
      gemini/zai/minimax do not).
      usage_error → nothing was sent; detail names the fix.
    If no envelope appears and the process is gone, review-log.txt says what
      happened. To cancel: kill "$(cat <WORKDIR>/review-pid.txt)"

The `[--model <id>]` / `[--effort <value>]` brackets show the template's
general form only — the message you emit contains a concrete command with the
brackets resolved: each flag present or absent, never literal. `launch.txt`
gets the same concrete command (whitespace/line-wrapping aside).

    STATUS: FAILED — <no target supplied | cannot read target: <path> | cannot
      write prompt file: <error> | diff review requested but no diff file supplied>
    <one line on what happened. No-target: no $ARGUMENTS reached this fork and
      nothing in context identified a target; nothing was prepared or sent. Diff
      case: save it first — git diff > <file> — and re-invoke with that path.>
    MAIN SESSION: re-invoke with the target in args. If forked invocations keep
      arriving empty, skip the fork and drive the runner yourself:
      1. Write the review prompt (your question + the file contents, inlined) to
         <scratchpad>/second-opinion-<slug>/prompt.txt
      2. Launch as a BACKGROUND Bash task (a foreground call dies at 10 minutes
         and orphans the runner):
         rm -f <dir>/review-envelope.json <dir>/review-text.md && \
         DEADLINE=5400 python3 <skill-dir>/scripts/run-request.py --long \
           --prompt-file <that file> --effort low kimi <dir>/review
         (swap the provider argument to reroute — kimi/openai/deepseek/xai take
         --effort, gemini/zai/minimax do not; add --model <id> for a specific
         model)
      3. <dir>/review-envelope.json appearing IS the completion signal — read
         its status first; the review lands at review-text.md.

In both templates, emit `<skill-dir>` resolved to this skill's real absolute
directory (your skill-load context names it). In PREPARED, emit `<WORKDIR>`
resolved to the real absolute work directory — a PREPARED message containing
a literal placeholder is a broken deliverable. The FAILED recipe's `<dir>`,
`<slug>`, and `<that file>` stay generic by design: no work directory exists
yet, and the main session fills them in.

**Relay the path, never the content.** The review is on disk once run; the
main session reads it there. Copying or summarizing it through a message can
only lose fidelity, and a summary drops the specific cited objection that
makes a second opinion worth having.

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
