# Changelog

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
