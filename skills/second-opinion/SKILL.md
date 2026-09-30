---
name: second-opinion
description: >-
  Get a second opinion from Kimi, Gemini, OpenAI, DeepSeek, xAI, GLM (z.AI), or
  MiniMax via API. Use for feedback on code, plans, documents, arguments, or any
  work product — also when stuck debugging or wanting a different perspective.
  The skill only PREPARES the request — the handoff message names the exact
  command for the main session to launch. Work lands in
  <session scratchpad>/second-opinion-*/ (prompt-<provider>.txt and
  launch-<provider>.txt when prepared; review-<provider>-text.md once run).
  The skill cannot see the conversation:
  put the target's file path, and any earlier reviews, in the args. To review
  uncommitted changes, save the diff to a file first and pass its path.
argument-hint: [file path and question]
allowed-tools: Read, Glob, Grep, Write
disallowed-tools: Bash, PowerShell, Agent, Skill, Workflow, ToolSearch, SendMessage, Monitor, CronCreate, RemoteTrigger
context: fork
model: sonnet
---

# Second Opinion Skill

**Request:** `$ARGUMENTS`

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
- Backends, routing and effort: [routing.md](routing.md)

## Choosing a backend

The backends, the routing table and effort are in `routing.md`, next to this
file (your skill-load context names the directory); `/second-opinion:direct`
reads the same file. **Read it in step 3, every time**: a route chosen
without it is a guess. If the Read fails, report FAILED and write no launch
command. You cannot check API keys (no shell); `routing.md` says what
happens when one is missing.

## When to Use

Use for the Request above, or proactively for: code, plans, or documents worth
reviewing; implementation plans before committing to an approach; debugging
when stuck >2 attempts; academic writing critique; anything where another
perspective might surface overlooked issues.

## Workflow

1. **Identify the target** from the **Request** line at the top. You cannot
   see the conversation that invoked you, so that line is your only source.
   An empty Request line, or one whose target is ambiguous or points back
   into the conversation ("the plan we discussed") → the FAILED template.
   Fail loudly; never ask (a fork has no user to answer) and never guess
   (reviewing the wrong thing reads as success).
2. **Read the target files** and inline their content in the prompt — no
   backend reads local files. Unreadable target → FAILED naming the path. A
   **diff review** requested without a saved diff file → FAILED naming the
   one-line fix (`git diff > <file>`, re-invoke with that path); you cannot
   run `git diff` and must not reconstruct a diff by Reading files.
3. **Read `routing.md`** in this skill's directory **and choose the
   backend** with its routing table, in the order it gives. A failed Read →
   FAILED naming the path; never route from memory. Add `--effort`
   only to depart from the runner's shared `high` — `low` for a quick or
   cheap check, higher where the backend offers it and the problem earns it
   (its "Effort" section); never for gemini. Pass `--model` only in the two
   cases its "Available Backends" names: the user named a model, or the
   chosen routing row names a non-default one (in-depth review →
   `gpt-6-sol`).
4. **Pick a fresh WORKDIR, per provider.** Every file this step writes is
   named for the provider step 3 chose — `prompt-<provider>.txt`,
   `launch-<provider>.txt`, and (in the launch command itself)
   `review-<provider>-*` — so that two forks reviewing the *same* target for
   *different* providers never touch each other's files, even if they end
   up in the same WORKDIR. That's deliberate: it's the normal way several
   providers' opinions get requested at once, and it should need no
   coordination between the forks doing it.

   Candidates, in order: `<session scratchpad>/second-opinion-<slug>`, then
   the same name with `-2`, `-3`, …. Probe each candidate with **two Reads,
   both with `limit: 1`**: `<candidate>/prompt.txt` (no provider — this is
   `/second-opinion:direct`'s file, never a fork's; it only ever exists
   because a direct session claimed this candidate first) and
   `<candidate>/prompt-<provider>.txt`.
   - Both say the file does not exist → fresh; this is your candidate.
   - Either Read returns content, or says the file is empty → taken —
     by a direct session (bare `prompt.txt`) or by an earlier request for
     *this same provider* (`prompt-<provider>.txt`); probe the next
     candidate either way. (A *different* provider's `prompt-<other>.txt`
     existing here does not count as taken — that's a sibling review of the
     same target, not a conflict.)
   - Anything else → FAILED, `cannot write prompt file: <what Read said>`.

   A taken candidate belongs to an earlier request; reusing it would let
   your launch command's `rm -f` delete that request's review. **Write** the
   composed prompt (see Prompt Construction) to `<WORKDIR>/prompt-<provider>.txt`.
   Then **Write the exact launch command — the same line that goes in the
   PREPARED message — to `<WORKDIR>/launch-<provider>.txt`**. Write creates
   the directory for you. No heredoc, no escaping, no jq.

   **Then confirm you actually own it: Read BOTH files back — `prompt-<provider>.txt`
   and `launch-<provider>.txt` — and compare each to what you just wrote**
   (Read prefixes each line with a line number for display — that numbering
   is not part of the file; compare the content, not the raw tool output).
   Check both, not launch alone: a same-provider racer can overwrite your
   prompt while leaving your launch command untouched, and a launch-only
   check would miss exactly that — you'd return PREPARED with a command that
   correctly names your model and effort but reads someone else's brief.
   - Both Reads return exactly what you wrote → proceed to return PREPARED.
   - Either Read returns something else, or says the file is missing → you
     lost the race. Do not delete or touch what is there — it is the other
     fork's real, in-flight claim. Probe the next candidate in the sequence
     (`-2`, then `-3`, …) and redo this entire step (probe, write both
     files, confirm) there.
   - Five losses in a row within this invocation → FAILED, `WORKDIR
     contention: lost the race on 5 consecutive candidates`.

   Be precise about what this catches and what it doesn't. It catches a
   same-provider racer whose overwrite lands between your write and your
   read-back — regardless of whether their content differs from yours, not
   only when it's identical. It **cannot** catch one that lands *after* your
   read-back passes: nothing stops a write in the instant between that Read
   and this fork's final message, with or without Bash. That narrower case
   — two same-provider forks each finishing their own write-then-verify
   before the other's overwrite arrives — is not fixable with Read and
   Write alone; it needs an atomic primitive this fork does not have. It
   requires a genuine duplicate dispatch to the same provider on the same
   target, not just several providers requested together, so treat it as
   rare, not as closed.
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
    prompt: <WORKDIR>/prompt-<provider>.txt   (command also saved at
      <WORKDIR>/launch-<provider>.txt)
    backend: <provider>, model <id, or "runner default — the envelope reports it">,
      reasoning_effort <value, or "runner default high", or "none — gemini">
    MAIN SESSION — launch this as a BACKGROUND Bash task (it may run up to 90 min;
      a foreground call dies at 10 minutes and orphans the runner):
      rm -f <WORKDIR>/review-<provider>-envelope.json \
        <WORKDIR>/review-<provider>-text.md \
        <WORKDIR>/review-<provider>-request.json && \
      DEADLINE=5400 python3 <skill-dir>/scripts/run-request.py --long \
        --prompt-file <WORKDIR>/prompt-<provider>.txt [--model <id>] [--effort <value>] \
        <provider> <WORKDIR>/review-<provider>
    Every filename this fork writes is provider-qualified — prompt, launch
      command and output base alike — so a WORKDIR shared with another
      *provider's* request that happened to probe the same candidate (see
      step 4) never collides: each provider's files are its own, matching
      the pattern `/second-opinion:direct` already uses for two runs in one
      WORKDIR. A same-provider request sharing the candidate is a different
      case — step 4's own scoping covers it.
    outputs, all next to prompt-<provider>.txt: review-<provider>-envelope.json
      (the outcome — its appearance after this launch IS the completion
      signal; read status first), review-<provider>-text.md (the review),
      review-<provider>-log.txt (run/attempt trace)
    status guide: completed → read text_path; the review is the deliverable, not
      reproduced or summarized here — treat it as one data point, not authority.
      partial → real output cut early: completed findings are valid; discard the
      final truncated one (it can reverse in the half that never arrived).
      failed → error_class bad_request/not_found/genuine auth/timeout_budget/
      output_cap are final — fix what detail names;
      rate_limit/server_error/network/timeout/empty may succeed on relaunch. The
      prompt's content is reusable for a different provider, but not the file
      itself: check prompt-<new provider>.txt in this WORKDIR does not
      already exist before copying to it — a legitimate sibling review for
      that provider may already be there — and if it does, swap to a fresh
      WORKDIR (or a fresh candidate suffix) instead of overwriting it. Name
      the new provider consistently in --prompt-file and the output base
      (drop --effort when swapping to gemini — it is the one backend that
      refuses the flag).
      usage_error → nothing was sent; detail names the fix.
    If no envelope appears and the process is gone, review-<provider>-log.txt says
      what happened. To cancel: kill the pid in review-<provider>-pid.txt, next
      to prompt-<provider>.txt.

The `[--model <id>]` / `[--effort <value>]` brackets show the template's
general form only — the message you emit contains a concrete command with the
brackets resolved: each flag present or absent, never literal.
`launch-<provider>.txt` gets the same concrete command (whitespace/line-wrapping
aside).

    STATUS: FAILED — <no target supplied | cannot read target: <path> | cannot
      read routing file: <path> | cannot write prompt file: <error> | diff
      review requested but no diff file supplied | WORKDIR contention: lost
      the race on 5 consecutive candidates>
    <one line on what happened. No-target: the Request line named no target
      this fork can read (it cannot see the conversation); nothing was
      prepared or sent. Routing file: the plugin's install is incomplete;
      reinstall it. Diff
      case: save it first — git diff > <file> — and re-invoke with that path.
      Contention case: something is claiming this provider's WORKDIR files
      faster than this fork can win one — likely two /second-opinion forks
      both requesting this same provider on the same target at once; no
      command was ever confirmed as this fork's own, so treat it as nothing
      was sent, though losing attempts may have left orphaned files behind.>
    MAIN SESSION: re-invoke with the target's file path in the args. If it keeps
      failing with a path in the request, use /second-opinion:direct, which
      launches the runner from the main session. Routing file: reinstall the
      plugin first; /second-opinion:direct reads the same file.

In PREPARED, emit `<skill-dir>` resolved to this skill's real absolute
directory (your skill-load context names it) and `<WORKDIR>` resolved to the
real absolute work directory — a PREPARED message containing a literal
placeholder is a broken deliverable. FAILED names no runner path: the
direct skill resolves its own.

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
3. **Earlier reviews**, when the request says any were done, on this
   version or an earlier one: one line, `Earlier reviews, in the
   requester's words: <words>`, where `<words>` is the request's clause
   about them (who reviewed, and anything it says they found), copied
   character for character; line breaks become spaces. For the request
   "second in-depth opinion; OpenAI already reviewed" the line is:

       Earlier reviews, in the requester's words: OpenAI already reviewed

   and for "second opinion on the parser, OpenAI said the retry loop never
   ends":

       Earlier reviews, in the requester's words: OpenAI said the retry loop never ends

   Add nothing to those words anywhere in the prompt: no model, depth,
   effort or finding they do not state. You know only the request's words, and the
   routing table says what a review would use, not what an earlier one did
   use. "A second opinion" alone names no earlier review.
4. **The questions**: what kind of feedback you want.

In this shape:

    I'm working on [TASK]. My current approach is [APPROACH].
    Files to review: [THE TARGET, INLINED]
    [THE EARLIER-REVIEWS LINE; omit if none]
    Questions:
    1. What problems do you see with this approach?
    2. What edge cases might I be missing?
    3. Is there a simpler solution I'm overlooking?

Context budgets (2026-09-25; each provider's `/models` where it reports one,
else its docs): every default model takes ~1M tokens; xAI's non-default
`grok-4.7` takes 500k. Cost rises with size for MiniMax and xAI (see the
long-documents row in `routing.md`), so for very large content include only
the relevant
sections where you can.
