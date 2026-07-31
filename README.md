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

Every invocation runs the same way: the skill *prepares* the review — it
writes the prompt and hands the session an exact command to launch it as a
background task — rather than running it itself. The review then runs outside
the skill, lands on disk once it finishes, and Claude reads it from there.

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
cost proportionally more. Every review runs as one background API call,
bounded by a 90-minute deadline. z.AI and MiniMax pricing: see their provider
docs.

## Updates

Provider model lineups change faster than plugin releases. The shipped
defaults are verified as of 2026-07; when a provider ships a new model, point
the skill at it with an env var instead of waiting for an update:

    export SECOND_OPINION_KIMI_MODEL=...      # likewise _GEMINI_, _OPENAI_,
    export SECOND_OPINION_DEEPSEEK_MODEL=...  # _XAI_, _ZAI_, _MINIMAX_

The override is honored by the runner at launch (build mode). One caveat: the
runner's unset-effort protection (which defaults `kimi-k3` to `"low"`) is
keyed to the model ids it ships with, not to whatever a
`SECOND_OPINION_*_MODEL` override points at — the skill already passes
`--effort` explicitly for kimi/openai/deepseek/xai, so this mainly matters if
you drive the runner by hand: set `--effort`/`reasoning_effort` yourself
whenever you override a default model.

## Documentation

- [skills/second-opinion/README.md](skills/second-opinion/README.md) — usage,
  model table, how reviews execute
- [skills/second-opinion/api-reference.md](skills/second-opinion/api-reference.md)
  — endpoints, request shapes, measured provider behavior
- [skills/second-opinion/SKILL.md](skills/second-opinion/SKILL.md) — the skill
  itself (what Claude follows)
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pieces fit: fork, runner, the files
  a run leaves, and what survives what

## Troubleshooting

- **"`<PROVIDER>_API_KEY` not set"** — the key isn't in the environment Claude
  Code runs in; see Requirements above.
- **The review's envelope reports `failed` with an `error_class`** — the fork
  never runs a review itself, so this arrives only via `review-envelope.json`
  (or the background task's own output), never as a fork reply. Deterministic
  classes (`bad_request`, `not_found`, genuine
  `auth`, `timeout_budget`) mean the request itself is wrong for that backend;
  transient ones (`rate_limit`, `server_error`, `network`, `timeout`) are worth
  retrying. Details and measured provider behavior:
  [skills/second-opinion/api-reference.md](skills/second-opinion/api-reference.md).
- **A reply of `STATUS: PREPARED` is not an error** — every review is
  deliberately handed back for the main session to launch in the background;
  the skill itself never runs one. (Breaking change from 0.1.x: earlier
  releases replied `STATUS: NOT-RUN`, and only for large or high-reasoning
  requests — small ones ran synchronously inside the fork. 0.2.0 removed that
  split; every review now takes the same PREPARED path.)
- **The skill replies that it is "waiting for" or "monitoring" a background
  review** — it cannot be: a forked skill's final message is its last word,
  and the fork never launches anything itself — it only prepares
  `prompt.txt` and `launch.txt` and hands the command to the main session. If
  the main session already launched the run, the outcome lands on disk once it
  finishes — look in the session's scratchpad directory for
  `second-opinion-*/review-envelope.json`, which says how the run ended and
  where its text is, with `review-text.md` beside it. If it was never launched
  (the fork ended before the command ran, or the command was lost), the work
  is still recoverable: `prompt.txt` and `launch.txt` sit in that same
  directory — `launch.txt` holds the exact command, byte-identical to what the
  PREPARED message showed.
- **"No task found with ID: second-opinion-second-opinion" (non-Anthropic
  driver only)** — this plugin targets Claude Code running on Anthropic models.
  The skill runs as a forked background task, and on a standard Anthropic driver
  its PREPARED handoff is delivered back to the main session automatically. If
  you point Claude Code at a non-Anthropic model endpoint (`ANTHROPIC_BASE_URL`,
  e.g. a Kimi/Moonshot-backed setup), that harness may not surface the forked
  skill's completion to the parent — so the main session can error trying to
  poll for it, never seeing the handoff, and nothing gets launched. The fork's
  work is still on disk: `.../second-opinion-<slug>/launch.txt` holds the exact
  command it prepared — run it yourself as a background Bash task (see the
  empty-args recipe below for the shape), and `review-envelope.json` appearing
  in that same directory is the completion signal. This affects any forked
  skill under such a setup, not just this one.
- **A forked review returns a question, or `STATUS: FAILED — no target
  supplied`, instead of a review** — the target argument never reached the
  forked skill, so it had nothing to review. This is an upstream argument-delivery
  failure (the harness didn't pass the invocation's `args` into the fork), not
  the runner — nothing was sent to any backend. Re-invoking may work; if it keeps
  happening, skip the fork and drive the runner yourself:
  1. Write the review prompt (your question + the file contents, inlined) to
     `<dir>/prompt.txt`, where `<dir>` is
     `<scratchpad>/second-opinion-<slug>`.
  2. Launch as a BACKGROUND Bash task (a foreground call dies at 10 minutes
     and orphans the runner):

         rm -f <dir>/review-envelope.json <dir>/review-text.md && \
         DEADLINE=5400 python3 <runner> --long \
           --prompt-file <dir>/prompt.txt --effort low kimi <dir>/review

     (swap the provider argument to reroute — kimi/openai/deepseek/xai take
     `--effort`, gemini/zai/minimax do not; add `--model <id>` for a specific
     model). If you installed from the marketplace, `<runner>` is
     `<claude-config-dir>/plugins/cache/ai4phi/second-opinion/<version>/skills/second-opinion/scripts/run-request.py`;
     from a clone it is `skills/second-opinion/scripts/run-request.py`.
  3. `<dir>/review-envelope.json` appearing IS the completion signal — read
     its status first; the review lands at `review-text.md`. Full envelope,
     status, and gate details:
     [skills/second-opinion/api-reference.md](skills/second-opinion/api-reference.md).

  This affects any forked skill that takes an argument, not just this one.
- **Sanity-check the runner itself** by running the unit tests below (no
  network, no keys needed).

## Using a partial review

A run interrupted mid-stream — by a timeout or otherwise — still leaves real
work on disk, reported as status `partial` in the envelope: normally N
complete findings plus one cut mid-sentence. Use it rather than discarding it:

- **The completed findings are valid.** Act on them.
- **Never act on the truncated final item.** A halted sentence can reverse
  itself in the half that never arrived ("a race condition — *unless* the
  caller holds the lock").
- **Never present a partial as complete** when relaying it onward.
- **Enough?** If the completed findings are self-contained and give you
  concrete changes, act on them and move on.
- **More expected?** (It announced eight problems and you have three, or it
  was cut inside the central argument.) Fix what you already know about
  first, then re-run — the next review then sees the corrected state instead
  of repeating findings you already fixed. Re-running immediately just pays
  twice for the same N.
- **Repeated truncation at the same place means the target is too big** —
  split it into smaller reviews.

Envelope, status, and gate details:
[skills/second-opinion/api-reference.md](skills/second-opinion/api-reference.md).

## Development

Unit tests for the runner (gate, error classification, envelope contract):

    python3 -m unittest discover -s tests -v

The tests talk to a local HTTP server on `127.0.0.1`. Behind a corporate
proxy, make sure loopback is excluded (`export no_proxy=127.0.0.1`), or
`urllib` will route the test traffic into the proxy.

## License

[MIT](LICENSE)
