# Changelog

## 0.1.0 — 2026-07

Initial release.

- Skill with five backends: Kimi (`kimi-k3`, default), Gemini, OpenAI,
  DeepSeek, xAI.
- Streaming runner (`scripts/run-request.py`, stdlib-only) with classified
  retries, a size/effort gate against orphaned long runs, partial-output
  recovery, and a single-JSON-envelope contract.
- Per-provider default-model overrides via `SECOND_OPINION_<PROVIDER>_MODEL`.
- Model tables and provider behavior verified 2026-07.
