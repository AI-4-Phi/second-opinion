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
schedule, or delegate something, it is not yours to use. Your tools are Read
and Write, plus Glob and Grep in builds that have them (some have neither);
your deliverable is one final message.

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
| Kimi | `MOONSHOT_API_KEY` | (none — Moonshot documents `reasoning_effort` for `kimi-k3` only) |
| Gemini | `GEMINI_API_KEY` | (none) |
| OpenAI | `OPENAI_API_KEY` | `gpt-6-sol` (in-depth review; the default `gpt-6-luna` is the quick and general-purpose check) |
| DeepSeek | `DEEPSEEK_API_KEY` | (none) |
| xAI | `XAI_API_KEY` | `grok-4.7` (listed, not recommended: the slowest and priciest per review tested) |
| z.AI | `ZAI_API_KEY` | `glm-5.3-flash` (listed, not recommended: in testing it judged a planted bug's code correct). A `/models` listing isn't access ([api-reference.md](api-reference.md)) |
| MiniMax | `MINIMAX_API_KEY` | (none) |

Per-provider **default models live in the runner**
(`scripts/run-request.py`, `DEFAULT_MODELS`, verified 2026-09) and are
resolved at launch: `--model` flag, else `SECOND_OPINION_<PROVIDER>_MODEL`
from the environment, else the built-in default. So pass `--model` in exactly
two cases: the user named a model — a built-in default included, since the
flag is what keeps an env override from replacing the model they named — or
the routing row you chose names a model that is not that provider's runner
default (today only `gpt-6-sol`). Otherwise omit it. An override env var
needs no special handling for effort: the runner's default is keyed to the
provider, not to the model id, so an overridden model gets the same `high`.

**Default backend: OpenAI.** Its runner default, `gpt-6-luna`, is the quick
and general-purpose check; an in-depth review goes to `gpt-6-sol` (see the
routing table). Use another backend when the user asks or for an additional
independent perspective — seven families means up to seven independent
opinions. You cannot check API keys (no shell); if the chosen backend's key
turns out to be missing, the runner reports it seconds after launch and the
main session reroutes.

### Routing guidance

| Situation | Prefer |
|-----------|--------|
| Quick or general-purpose check (default) | OpenAI (runner default `gpt-6-luna`) |
| In-depth review: the user asks for a thorough or in-depth review, or the target is a spec, design, implementation plan, whole-branch or pre-merge diff, completed implementation, or debugging that is stuck | OpenAI `--model gpt-6-sol`. For a second in-depth opinion, Kimi, and z.AI third — but for a spec or document, z.AI second and Kimi third (the maintainer's ranking). The default `high` covers depth; go higher only for the hardest problems (see Effort) |
| Fast feedback | OpenAI (its default `gpt-6-luna`), then Gemini |
| Cheap feedback | OpenAI (its default `gpt-6-luna`), DeepSeek, or xAI. xAI's default `grok-4.3` is cheap and fast, but check what it reports: in testing it asserted bugs that were not there. Kimi is neither fast nor cheap |
| File-heavy or long documents | Any default (each takes ~1M tokens; MiniMax doubles its price past 512k input tokens, xAI past 200k) |
| Another independent opinion | Any unused family — different family, different blind spots |
| No OpenAI/Kimi credits | Gemini (free tier) or DeepSeek (near-free) |

Apply the table in this order. (1) A provider or model the user names wins;
so does an explicit ask for a quick, fast or cheap check. (2) Otherwise the
in-depth row applies when its trigger matches; when unsure, the request is
not in-depth, and the default quick check applies. (3) "Second" and "third"
in-depth opinions count the external in-depth reviews of the same target
that the request names as done ("OpenAI already reviewed"), that you can see
in this conversation, or the number the user asks for up front: with none,
the review goes to `gpt-6-sol`, even when the user says "a
second opinion" (the skill's name, not a count). (4) The long-documents row
only adjusts cost; it never replaces the route chosen above.

**Effort:** the runner sends `reasoning_effort: high` to every backend that
takes it, so **omit `--effort`** and the review runs at that shared level
whichever provider you picked. Pass **`--effort low`** only when the user
wanted a quick or cheap check. Higher than `high` (`xhigh` on OpenAI / xAI,
`max` on kimi / DeepSeek / z.AI) is for genuinely hard problems and only where
the backend offers it. Never use `medium` as a middle ground: kimi and z.AI
reject it, and DeepSeek accepts it but does not document it. **Never** pass
`--effort` for gemini: it has no such parameter and the runner refuses the
flag.

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
3. **Choose the backend** from the routing table above. Add `--effort` only
   to depart from the runner's shared `high` — `low` for a quick or cheap
   check, higher where the backend offers it and the problem earns it (see
   "Effort" above); never for gemini. Pass `--model` only in the two cases
   "Available Backends" names: the user named a model, or the chosen routing
   row names a non-default one (in-depth review → `gpt-6-sol`).
4. **Pick a fresh WORKDIR.** Candidates, in order:
   `<session scratchpad>/second-opinion-<slug>`, then the same name with
   `-2`, `-3`, …. Probe each by **Reading `<candidate>/prompt.txt` with
   `limit: 1`**:
   - Read says the file does not exist → fresh; this is your WORKDIR.
   - Read returns content, or says the file is empty → taken; probe the next.
   - Anything else → FAILED, `cannot write prompt file: <what Read said>`.

   A taken WORKDIR belongs to an earlier request; reusing it would let your
   launch command's `rm -f` delete that request's review. **Write** the
   composed prompt (see Prompt Construction) to `<WORKDIR>/prompt.txt`.
   Then **Write the exact
   launch command — the same line that goes in the PREPARED message — to
   `<WORKDIR>/launch.txt`**. Write creates the directory for you. No
   heredoc, no escaping, no jq.
5. **Return the PREPARED message.** That message is the entire deliverable.
   Its command must run **verbatim with zero edits**: it starts with the
   `rm -f` prefix, uses this skill's real absolute directory for
   `<skill-dir>` (your skill-load context names it), includes `--model <id>`
   exactly when step 3 chose one, includes `--effort <value>`
   exactly when step 3 departed from the default, and contains no
   placeholders, brackets, or editorial notes.

## Final-message contract (mandatory — the only two templates)

The fork's final message is the ONLY thing that survives it. "Running",
"waiting", and "monitoring" are banned — you cannot truthfully say them about
anything. Never substitute your own review; if you cannot prepare, report
FAILED and why.

    STATUS: PREPARED (review not yet run — the main session must launch it)
    target: <one line: what is being reviewed>
    prompt: <WORKDIR>/prompt.txt   (command also saved at <WORKDIR>/launch.txt)
    backend: <provider>, model <id, or "runner default — the envelope reports it">,
      reasoning_effort <value, or "runner default high", or "none — gemini">
    MAIN SESSION — launch this as a BACKGROUND Bash task (it may run up to 90 min;
      a foreground call dies at 10 minutes and orphans the runner):
      rm -f <WORKDIR>/review-envelope.json <WORKDIR>/review-text.md \
        <WORKDIR>/review-request.json && \
      DEADLINE=5400 python3 <skill-dir>/scripts/run-request.py --long \
        --prompt-file <WORKDIR>/prompt.txt [--model <id>] [--effort <value>] \
        <provider> <WORKDIR>/review
    outputs, all next to prompt.txt: review-envelope.json (the outcome — its
      appearance after this launch IS the completion signal; read status
      first), review-text.md (the review), review-log.txt (run/attempt trace)
    status guide: completed → read text_path; the review is the deliverable, not
      reproduced or summarized here — treat it as one data point, not authority.
      partial → real output cut early: completed findings are valid; discard the
      final truncated one (it can reverse in the half that never arrived).
      failed → error_class bad_request/not_found/genuine auth/timeout_budget/
      output_cap are final — fix what detail names;
      rate_limit/server_error/network/timeout/empty may succeed on relaunch. The
      prompt file is reusable as-is; the provider argument is swappable (drop
      --effort when swapping to gemini — it is the one backend that refuses
      the flag).
      usage_error → nothing was sent; detail names the fix.
    If no envelope appears and the process is gone, review-log.txt says what
      happened. To cancel: kill the pid in review-pid.txt, next to prompt.txt.

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
         rm -f <dir>/review-envelope.json <dir>/review-text.md \
           <dir>/review-request.json && \
         DEADLINE=5400 python3 <skill-dir>/scripts/run-request.py --long \
           --prompt-file <that file> openai <dir>/review
         (this runs OpenAI's quick-check default; add --model gpt-6-sol for
         an in-depth review. Swap the provider argument to reroute; add
         --effort low for a quick check, or --model <id> for a specific
         model. Gemini is the one backend that refuses --effort)
      3. <dir>/review-envelope.json appearing IS the completion signal — read
         its status first; the review lands at review-text.md.

In both templates, emit `<skill-dir>` resolved to this skill's real absolute
directory (your skill-load context names it). In PREPARED, emit `<WORKDIR>`
resolved to the real absolute work directory — a PREPARED message containing
a literal placeholder is a broken deliverable. The FAILED recipe's `<scratchpad>`,
`<dir>`, `<slug>`, and `<that file>` stay generic by design: no work directory
exists yet, and the main session fills them in.

**Relay the path, never the content.** The review is on disk once run; the
main session reads it there. Copying or summarizing it through a message can
only lose fidelity, and a summary drops the specific cited objection that
makes a second opinion worth having.

## Prompt Construction

The prompt goes to an outside provider. It has exactly these four parts, in
this order, and nothing else:

1. **The work**, in a sentence or two, taken from the request and the target.
2. **The target from step 1, inlined**, however it reached you. Session
   instructions, CLAUDE.md files, memory, git state and files the request
   does not name are not part of it.
3. **Earlier reviews**, when the request or this conversation names them:
   what that source states about them, e.g. "OpenAI already reviewed this".
   The routing table tells you what a review would use, not what an earlier
   one did use.
4. **The questions**: what kind of feedback you want.

In this shape:

    I'm working on [TASK]. My current approach is [APPROACH].
    Files to review: [THE TARGET, INLINED]
    [EARLIER REVIEWS, as the request or conversation states them; omit if none]
    Questions:
    1. What problems do you see with this approach?
    2. What edge cases might I be missing?
    3. Is there a simpler solution I'm overlooking?

Context budgets (2026-09-25; each provider's `/models` where it reports one,
else its docs): every default model takes ~1M tokens; xAI's non-default
`grok-4.7` takes 500k. Cost rises with size for MiniMax and xAI (see the
long-documents row), so for very large content include only the relevant
sections where you can.
