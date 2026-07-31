# CLAUDE.md

Claude Code plugin: the `second-opinion` skill + `run-request.py` runner.

- Tests: `python3 -m unittest discover -s tests` — stdlib only, like the
  runner itself. No pytest, no pip installs; keep the no-dependencies promise.
- Tests import the hyphenated `run-request.py` via importlib and talk to a
  local HTTP server; no network, no real keys (env is scrubbed via RUNNER_ENV).
- Every provider/model claim in the docs must be empirically verified and
  date-stamped ("verified YYYY-MM"); prefer `SECOND_OPINION_<PROVIDER>_MODEL`
  env overrides over adding model rows — each row is a claim that decays.
  Ground truth for model ids: `GET /models` on the provider endpoint.
- The `SECOND_OPINION_<PROVIDER>_MODEL` overrides are honored by the RUNNER's
  build mode (model resolution: `--model` > env > `DEFAULT_MODELS`); legacy
  mode deliberately never reads them, and the fork passes `--model` only for
  explicitly requested non-default models.
- One home per fact: the envelope statuses/exit codes, the gate's blocking
  conditions, the reader rule, and the orphan-kill live in api-reference.md;
  SKILL.md keeps routing and the fork contract (PREPARED/FAILED) only. Don't
  duplicate.
- strip_think() is minimax-scoped by design — the verified provider behavior
  behind that lives in its docstring in run-request.py; don't restate it here.
