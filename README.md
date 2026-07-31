# second-opinion

A [Claude Code](https://claude.com/claude-code) plugin that gets a second
opinion on Claude's work from an external model — Kimi, Gemini, OpenAI,
DeepSeek, xAI, GLM (z.AI), or MiniMax — via their REST APIs. Reviews code, plans, drafts,
arguments, or any other work product; Claude reads the review and remains the
decision-maker.

    /second-opinion is this refactoring approach sound?
    /second-opinion ask DeepSeek to review this draft
    /second-opinion with Gemini 2.5-pro: review all the files in this dir

Claude also invokes it proactively when a plan or piece of work is worth an
outside check.

## ⚠️ Where your content goes

**The content you ask to have reviewed is sent to the third-party provider you
route to** (Moonshot AI, Google, OpenAI, DeepSeek, xAI, Z.AI, or MiniMax),
under that provider's API data terms. Nothing leaves your machine until the skill runs,
and each request goes to exactly one backend — but do not route confidential
material to a provider you wouldn't paste it into directly, and check the
provider's data-retention/training policy if that matters for your content.

## Install

From the [ai4phi marketplace](https://github.com/AI-4-Phi/plugins):

    /plugin marketplace add AI-4-Phi/plugins
    /plugin install second-opinion@ai4phi

To remove it: `/plugin uninstall second-opinion@ai4phi`.

## Requirements

Developed and tested on macOS and Linux. Windows is untested (the runner's
orphan-cleanup uses POSIX signals and `kill`); WSL should behave like Linux.

- `python3` — the runner is stdlib-only: no packages, no venv.
- An API key, exported in your environment, for each backend you want (any
  subset works; when the default backend has no key, the skill routes to one
  that does):

| Backend | Env var | Get a key |
|---|---|---|
| Kimi (default) | `MOONSHOT_API_KEY` | [platform.kimi.ai](https://platform.kimi.ai/) |
| Gemini | `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) (free tier covers `gemini-2.5-pro`) |
| OpenAI | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com/api-keys) |
| DeepSeek | `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| xAI | `XAI_API_KEY` | [console.x.ai](https://console.x.ai/) |
| z.AI (GLM) | `ZAI_API_KEY` | [docs.z.ai](https://docs.z.ai/) |
| MiniMax | `MINIMAX_API_KEY` | [platform.minimax.io](https://platform.minimax.io/) |

Put the `export` in your shell profile (`.zshrc`, `.bashrc`, or a secrets file
it sources) so every Claude Code session inherits it. If Claude Code is
launched from a desktop app rather than a terminal, it may not see
shell-profile exports — start it from a terminal, or set the vars in Claude
Code's settings (`env` in `settings.json`).

## Cost

Each review is one API call to the chosen provider, billed to your key. Rough
per-review order of magnitude (2026-07 prices, a typical few-thousand-token
review): Kimi `kimi-k3` is the priciest ($3/M input, $15/M output — usually
cents per review); DeepSeek and Gemini Flash are near-free; Gemini
`gemini-2.5-pro` has a free tier. Large documents at high reasoning effort
cost proportionally more — the skill warns and routes those explicitly. z.AI
and MiniMax pricing: see their provider docs.

## Updates

Provider model lineups change faster than plugin releases. The shipped
defaults are verified as of 2026-07; when a provider ships a new model, point
the skill at it with an env var instead of waiting for an update:

    export SECOND_OPINION_KIMI_MODEL=...     # likewise _GEMINI_, _OPENAI_,
                                             # _DEEPSEEK_, _XAI_

## Documentation

- [skills/second-opinion/README.md](skills/second-opinion/README.md) — usage,
  model table, how long reviews execute
- [skills/second-opinion/api-reference.md](skills/second-opinion/api-reference.md)
  — endpoints, request shapes, measured provider behavior
- [skills/second-opinion/SKILL.md](skills/second-opinion/SKILL.md) — the skill
  itself (what Claude follows)
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pieces fit: fork, runner, the files
  a run leaves, and what survives what

## Troubleshooting

- **"`<PROVIDER>_API_KEY` not set"** — the key isn't in the environment Claude
  Code runs in; see Requirements above.
- **The skill reports FAILED with an `error_class`** — deterministic classes
  (`bad_request`, `not_found`, genuine `auth`, `timeout_budget`) mean the
  request itself is wrong for that backend; transient ones (`rate_limit`,
  `server_error`, `network`, `timeout`) are worth retrying. Details and
  measured provider behavior:
  [skills/second-opinion/api-reference.md](skills/second-opinion/api-reference.md).
- **A reply of `STATUS: NOT-RUN` is not an error** — large or high-reasoning
  requests are deliberately handed back for the main session to run in the
  background.
- **The skill replies that it is "waiting for" or "monitoring" a background
  review** — it cannot be, and no completion notification will arrive: the fork
  ended when it sent that message. The runner it started keeps going and does
  finish, so the outcome is on disk — look in the session's scratchpad directory
  for `second-opinion-*/review-envelope.json`, which says how the run ended and
  where its text is, with `review-text.md` beside it. Observed once on 0.1.1
  (2026-07-30); 0.1.2 removes the copy-pasteable background-launch line that
  invited it, has each handoff name the artifacts its run leaves, and writes that
  envelope file so a lost notification no longer loses the result.
- **"No task found with ID: second-opinion-second-opinion" (non-Anthropic
  driver only)** — this plugin targets Claude Code running on Anthropic models.
  The skill runs as a forked background task, and on a standard Anthropic driver
  its result is delivered back to the main session automatically. If you point
  Claude Code at a non-Anthropic model endpoint (`ANTHROPIC_BASE_URL`, e.g. a
  Kimi/Moonshot-backed setup), that harness may not surface the forked skill's
  completion to the parent — so the main session can error trying to poll for it.
  The review still ran and is on disk: read the `review-text.md` the skill wrote
  under its work dir (`.../second-opinion-<slug>/review-text.md`). This affects
  any forked skill under such a setup, not just this one.
- **A forked review returns a question, or `STATUS: FAILED — no target
  supplied`, instead of a review** — the target argument never reached the
  forked skill, so it had nothing to review. This is an upstream argument-delivery
  failure (the harness didn't pass the invocation's `args` into the fork), not
  the runner — nothing was sent to any backend. Re-invoking may work; if it keeps
  happening, skip the fork and drive the runner from the main session directly:
  build a `request.json` and run
  `<runner> <provider> <request.json> <out>` (add `--long` for large or
  high-effort requests). If you installed from the marketplace, `<runner>` is
  `<claude-config-dir>/plugins/cache/ai4phi/second-opinion/<version>/skills/second-opinion/scripts/run-request.py`;
  from a clone it is `skills/second-opinion/scripts/run-request.py`. The request
  shape and the short/long gate are in
  [SKILL.md](skills/second-opinion/SKILL.md). This affects any forked skill that
  takes an argument, not just this one.
- **Sanity-check the runner itself** by running the unit tests below (no
  network, no keys needed).

## Development

Unit tests for the runner (gate, error classification, envelope contract):

    python3 -m unittest discover -s tests -v

The tests talk to a local HTTP server on `127.0.0.1`. Behind a corporate
proxy, make sure loopback is excluded (`export no_proxy=127.0.0.1`), or
`urllib` will route the test traffic into the proxy.

## License

[MIT](LICENSE)
