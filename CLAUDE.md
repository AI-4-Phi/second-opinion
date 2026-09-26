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
  mode deliberately never reads them. The fork passes `--model` only when the
  user names a model (a built-in default included, so an env override cannot
  replace it) or when a routing row names a non-default model (in-depth →
  `gpt-6-sol`).
- One home per fact: the envelope statuses/exit codes, the gate's blocking
  conditions, the reader rule, and the orphan-kill live in api-reference.md;
  SKILL.md keeps routing and the fork contract (PREPARED/FAILED) only. Don't
  duplicate.
- strip_think() is minimax-scoped by design — the verified provider behavior
  behind that lives in its docstring in run-request.py; don't restate it here.
- Settled; don't re-propose (reasoning in the 0.1.2/0.2.0 commits): a fifth
  `status: "running"` envelope — it makes "an envelope exists" mean "started
  or ended" and destroys the invariant every consumer is written against (if
  liveness is ever wanted, a separate `-state.json`, never the envelope);
  `mkstemp`/`fsync` for the envelope write — `os.replace` gives exactly what
  the docs claim, "atomically replaced", not "durable" (revisit only if the
  runner ever writes into a shared directory); a launch-epoch or pid field in
  the envelope — the launch command's `rm -f` prefix already gets that
  property; `--system-file` or any other request-shape flag in build mode —
  legacy mode is the escape hatch.
- The fork's no-shell guarantee covers only tools this plugin can name. A
  session supplying exec-capable MCP tools is outside any disallow list's
  reach; SKILL.md's prose rule — if a tool would run, schedule, or delegate
  something, it is not yours to use — is what covers those.
