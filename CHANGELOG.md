# Changelog

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
