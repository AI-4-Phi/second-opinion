# Changelog

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
