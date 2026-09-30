---
name: direct
description: >-
  Use when a second-opinion review prompt is already written, when several
  providers should review the same prompt, when a reviewer must cite exact line
  numbers, for a second-round review that carries earlier findings, or when
  /second-opinion keeps failing although the request names a file. Launches the
  second-opinion runner from the main session. For an ordinary first review of
  a named file, use /second-opinion instead.
argument-hint: [providers and file paths]
---

# Second opinion, launched directly

You run the review yourself, in the main session, with the plugin's runner,
`<base directory>/../second-opinion/scripts/run-request.py`, where
`<base directory>` is the "Base directory for this skill" line above. The
request, if any, is on the `ARGUMENTS:` line after this text: it names
providers and files.

The prompt goes to an outside provider (see "Where your content goes" in the
plugin's README.md). You can see far more than you should send: the
conversation, CLAUDE.md files, memory, credentials. The prompt has exactly
these parts, in this order, and nothing else:

1. **The work**, in a sentence or two, described from the files under review.
   Do not quote or summarize the conversation, memory or instruction files.
2. **The files under review**, each one inlined: only the files the review is
   about, never credentials, environment files or unrelated dotfiles.
3. **Earlier reviews**, if any: for a later round, what they found, what you
   fixed, and your reasons for declining the rest, so the reviewer can
   challenge those too.
4. **The questions**: what kind of feedback you want.

## Steps

1. **Create a fresh work directory** with `mkdir` (no `-p`):
   `"<session scratchpad>/second-opinion-<slug>"`, and if that fails because
   the name exists, `-2`, `-3`, … until one succeeds; if it fails for any
   other reason, stop and report it. A taken name makes `mkdir` fail, so two
   direct sessions never share a directory. `/second-opinion` forks use the
   same names but have no `mkdir` (no Bash): each treats a bare `prompt.txt`
   in a candidate as taken and moves on — so your `mkdir` staking a
   candidate, followed eventually by writing `prompt.txt` in step 2, is what
   keeps forks out of it, the same as it always was. That exclusion only
   starts once `prompt.txt` is actually on disk: a fork whose probe lands in
   the narrow window after your `mkdir` but before your `prompt.txt` write
   won't see it yet and could write its own provider-qualified files into
   the directory you just claimed. Each fork also reads its own
   `prompt-<provider>.txt` and `launch-<provider>.txt` back after writing to
   catch a same-provider fork racing it for the same candidate.
2. **Build `"<dir>/prompt.txt"` in part order**, adding files with the shell
   rather than retyping them:
   - part 1 with a heredoc (`cat > "<dir>/prompt.txt" <<'END_OF_PART'`);
   - each file as a header line naming it, then its lines numbered:
     `echo "--- path/to/file ---" >> "<dir>/prompt.txt"` and
     `cat -n "path/to/file" >> "<dir>/prompt.txt"`;
   - parts 3 and 4 with an appending heredoc (`cat >> … <<'END_OF_PART'`).

   If a prompt is already written, check it against the four parts, copy it
   to `"<dir>/prompt.txt"`, and go on to step 3. Before launching, read the
   non-file parts once more for secrets and private notes.
3. **Launch one background Bash task per run**, all on the same prompt file,
   each with its own output base:

       DEADLINE=5400 python3 "<base directory>/../second-opinion/scripts/run-request.py" \
         --long --prompt-file "<dir>/prompt.txt" \
         [--model <id>] [--effort <level>] <provider> "<dir>/review-<provider>"

   Write the real base directory into each command: every Bash call starts a
   fresh shell, so a variable set in an earlier call is empty here.

   Two runs on one provider (say a quick and an in-depth OpenAI review) need
   different bases, such as `review-openai-quick` and `review-openai-sol`.
   Run each in the background: a foreground call dies at 10 minutes and
   orphans the runner. `--long` tells the runner's size and effort gate that
   you did. To relaunch a run, give it a new base (`review-kimi-2`): an old
   base's leftover envelope and text look like a finished run.
4. **Wait for each task's exit notification**; do not poll. The base's
   `-envelope.json` is the outcome: read its `status` first. The review is the
   base's `-text.md`. A `-log.txt`, a `-pid.txt` and an empty `-text.md`
   appear at launch; none of them is an outcome.

## Choosing providers and flags

`<provider>` is a provider name, not a model id: `openai`, `kimi`, `zai`,
`deepseek`, `xai`, `minimax`, `gemini`.

- **Which provider, model and effort for which review:** Read
  `<base directory>/../second-opinion/routing.md` before choosing them; the
  `/second-opinion` fork routes by the same file. If that Read fails, the
  plugin's install is incomplete: reinstall it rather than route from
  memory. Don't follow that skill's SKILL.md: it
  is the fork's contract (prepare only, no shell) and does not apply to you.
- **Models, effort levels, envelope statuses, error classes and provider
  quirks:** `<base directory>/../second-opinion/api-reference.md`.
