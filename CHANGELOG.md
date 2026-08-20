# Changelog

## 0.2.2 — 2026-08

- **z.AI default is now `glm-5.3`.** The access gate that blocked `glm-5.3` on
  standard API keys in 0.2.1 has lifted: on 2026-08-20 a live completion on a
  standard key succeeded (raw call and a full runner streaming pass, envelope
  `completed`, reasoning on by default, ~15 s on a small prompt). That is the
  promotion rule 0.2.1 set — a newer id moves in only after one live completion
  on it succeeds — firing as written; the rule itself is unchanged.
- Documentation plus the one-line default in `DEFAULT_MODELS`; the runner's
  logic is unchanged and its 125 tests still pass.

## 0.2.1 — 2026-08

- **z.AI re-verified 2026-08-16.** `glm-5.3` (launched ~2026-08-13) appears on
  `GET /api/paas/v4/models`, but a completion on a standard API key fails with
  error 1220, "You do not have permission to access glm-5.3" — at launch it is
  gated to the GLM Coding Plan / ZCode, with plain API access staged to follow.
  `glm-5.2` stays the z.AI default (control probe: completes fine, still
  reasons by default).
- **A listing is not access.** That falsifies the "newest on `/models` wins"
  rule the skill gave for the fast-moving glm-5.x line: promote a newer id only
  after one live completion on it succeeds. api-reference.md carries the
  finding; SKILL.md and the skill README keep a pointer to it.
- Documentation only — the runner is unchanged and its 125 tests still pass.

## 0.2.0 — 2026-07

The fork prepares, the main session launches. Every review used to run
*inside* the forked skill invocation, which meant a long review's outcome
depended on a fork obeying prose it could just as easily ignore — 0.1.2
existed to make that non-compliance recoverable, not to stop it happening.
0.2.0 removes the option: the fork's tools no longer include a shell, so it
cannot launch anything. It can only build the request and hand back a
concrete, zero-edit command for the main session to run.

- **Breaking: the skill never runs the review itself.** Every review — short
  or long — is launched by the main session from the fork's PREPARED
  handoff. The old `STATUS: NOT-RUN` / `COMPLETED` / `PARTIAL` fork replies
  are retired; a fork now only ever returns `PREPARED` or `FAILED`.
- **Breaking: fork toolset narrowed.** `disallowed-tools` on the skill
  frontmatter removes Bash, PowerShell, and the dispatch tools (Agent, Skill,
  Workflow, ToolSearch, SendMessage, Monitor, CronCreate, RemoteTrigger) from
  the fork, so it structurally cannot run the runner, spawn a subprocess, or
  hand the job to another agent — E1-verified 2026-07-31.
- **Breaking: no more silent key-fallback.** The 0.1.x fork pre-checked API
  keys and silently fell back to Gemini when the default backend's key was
  missing. The 0.2.0 fork cannot check keys — it has no shell — so a
  missing-key default-routed review now costs one failed launch (a typed
  `usage_error` naming the key and the resolved provider/model, seconds
  after launch) plus a reroute.
- **Added: runner build mode.** `run-request.py --prompt-file <path> [--model
  <id>] [--effort <level>] <provider> <output-base>` has the runner compose
  the API request body itself from a plain prompt file, instead of requiring
  a pre-assembled `request.json` (legacy mode, still supported). That's what
  makes the no-shell fork possible: the fork no longer has to build JSON by
  hand before handing off — it writes the prompt and the launch command, and
  build mode does the composing when the main session runs that command.
- **Added: `SECOND_OPINION_<PROVIDER>_MODEL` resolution in build mode.** The
  env override is read at build time when picking the model; legacy mode
  still never reads it.
- **Added: model-keyed low-effort injection for `kimi-k3`** — the old "always
  set `reasoning_effort` on kimi-k3" prose rule from the fork, now enforced
  in code at build time. **Added: gemini `--effort` validation** — gemini has
  no `reasoning_effort` parameter, so an `--effort` flag against a gemini
  target is a usage error rather than silently ignored.
- **Added: `os.makedirs` on the output base.** Both legacy and build mode
  now create missing output directories instead of failing on them.
- **Added: `<base>-request.json`**, the built request artifact, and
  **`launch.txt`**, the handoff command — byte-for-byte what the fork's
  PREPARED message tells the main session to run.
- **Added: self-clearing launch command.** The command in `launch.txt` opens
  with `rm -f` against the WORKDIR's stale `review-envelope.json` and
  `review-text.md` before it runs, so a second launch against a re-prepared
  WORKDIR can't be misread against leftovers from the first.
- **Changed:** legacy invocations with unknown `--flags` — previously
  swallowed silently and treated as positional arguments — are now a
  `usage_error`. Malformed-invocation error text is reworded to match.
- **Changed:** the gate's refusal message and its "size" reason are reworded.
  The old refusal text named "a skill fork" specifically; that framing
  stopped being true once forks lost the ability to run anything, so the
  wording is now mode-agnostic. The substrings every test pins — the prefix
  `long-path request refused: `, the remedy `trim the prompt`, the remedy
  `set reasoning_effort to "low"` — are unchanged.
- **Unchanged:** legacy CLI acceptance for every documented invocation, the
  envelope contract and file, the gate's size/effort thresholds, exit codes.
- **Removed:** the `jq` dependency and every `jq` invocation pattern from the
  docs. The fork used to build `request.json` by hand with a temp-file +
  `jq --rawfile` recipe; build mode does that composing now, so nothing
  shells out to `jq`.
- 59 new tests (125 total), covering build mode end-to-end and the strict
  CLI grammar (the narrowed fork toolset is verified by the manual E1 probe,
  not the unit suite).

## 0.1.2 — 2026-07

Long-path handoff hardening, and the runner's outcome becomes an artifact. On 0.1.1
a forked review launched its own background run instead of handing it back, ended by
saying it would wait for a completion notification that could not arrive, and left a
finished 10.9 KB review unread for ~45 minutes (2026-07-30, one of two long-path
invocations).

- **New: `<output-base>-envelope.json`.** The runner writes the same envelope it
  prints on stdout to disk as well, atomically, when a run reaches a terminal
  outcome — so the outcome survives a launcher that dies first. That file appearing
  is the completion signal, and it carries `status`, `text_path`, `chars`, `usage`
  or `error_class`. What its *absence* does and does not prove is documented in
  api-reference.md.
- **`emit()` hardened — a bug fix in its own right.** A failed stdout write (a
  `BrokenPipeError` when the reader is gone, i.e. precisely the orphan case) used to
  escape into the catch-all, which emitted a second envelope and then died with an
  uncaught traceback. Both sinks are now best-effort and `emit()` is terminal, so a
  dead reader cannot change a run's recorded outcome.
- A `usage_error` now leaves a file where before it left nothing: a main session
  that forgot `--long`, or ran with no API key, finds a typed explanation on disk
  instead of silence.
- Every final message names the artifacts the run left, where they exist — a failed
  run has only the log, and a run that never started has neither.
- New: ARCHITECTURE.md — components, channels, the files a run leaves, and what
  survives what.
- 12 new tests (66 total), led by regressions for the two runner bugs above.
- The NOT-RUN template no longer hands the fork a copy-pasteable
  `run_in_background: true` — the one call the skill forbids it to make. The
  requirement is now prose addressed to the main session, with the reason: a
  foreground Bash call dies at 10 minutes and orphans the runner.
- The skill's own description names the output glob, so the main session can find
  a long review's result even if the fork's final message tells it nothing.
- The long path no longer passes `ATTEMPTS=1`, so the runner's default of 4
  applies and a transient 429 is retried rather than ending the run. Cost: a
  failing long run can now use its full 90-minute `DEADLINE` instead of ~30
  minutes.
- What 0.1.2 guarantees is that a result is recoverable, not that a fork obeys:
  with one non-compliant run out of two observed, the compliance edits are
  unvalidated by design.

## 0.1.1 — 2026-07

- A forked review that receives no target now returns
  `STATUS: FAILED — no target supplied` instead of asking a clarifying question
  a fork has no user to answer. Empty `$ARGUMENTS` inside a fork is an upstream
  argument-delivery failure, observed once and not reproducible since; nothing
  is sent to any backend when it happens.
- README troubleshooting: how to recognize that failure, and how to drive
  `run-request.py` from the main session as a fallback (runner path given for
  both marketplace and clone installs).
- Documentation only — the runner is unchanged.

## 0.1.0 — 2026-07

Initial release.

- Skill with seven backends: Kimi (`kimi-k3`, default), Gemini, OpenAI,
  DeepSeek, xAI, z.AI (GLM), MiniMax.
- MiniMax M-series `<think>` chain-of-thought blocks stripped from review
  text (verified live on `MiniMax-M3`, 2026-07-23).
- Streaming runner (`scripts/run-request.py`, stdlib-only) with classified
  retries, a size/effort gate against orphaned long runs, partial-output
  recovery, and a single-JSON-envelope contract.
- Per-provider default-model overrides via `SECOND_OPINION_<PROVIDER>_MODEL`.
- Model tables and provider behavior verified 2026-07.
