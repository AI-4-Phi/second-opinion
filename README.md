# second-opinion

A [Claude Code](https://claude.com/claude-code) plugin that gets a second
opinion on Claude's work from an external model — Kimi, Gemini, OpenAI,
DeepSeek, xAI, GLM (z.AI), or MiniMax — via their REST APIs. Reviews code, plans, drafts,
arguments, or any other work product; Claude reads the review and remains the
decision-maker.

    /second-opinion is the refactoring in src/parser.py sound?
    /second-opinion ask DeepSeek to review drafts/intro.md
    /second-opinion in depth: review docs/plan.md

Name the file: the skill runs in a fork that cannot see the conversation,
so "review this plan" gives it nothing to find. Claude also invokes it
proactively when a plan or piece of work is worth an outside check.

Every `/second-opinion` invocation runs the same way: the skill *prepares*
the review — it writes the prompt and hands the session an exact command to
launch it as a background task — rather than running it itself. The review
then runs outside the skill, lands on disk once it finishes, and Claude reads
it from there.

A second skill, `/second-opinion:direct`, skips the preparing step: the main
session writes the prompt and launches the runner itself. Use it for several
providers on one prompt, files with real line numbers, or a second round that
carries the first round's findings.

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
| Kimi | `MOONSHOT_API_KEY` | [platform.kimi.ai](https://platform.kimi.ai/) |
| Gemini | `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) (free tier — see the [model table](skills/second-opinion/README.md#model-details)) |
| OpenAI (default) | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com/api-keys) |
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

Each review is one API call to the chosen provider, billed to your key.
Reasoning is billed as output, so a model's output price matters more than
its input price. Every review runs as one background
API call, bounded by a 90-minute deadline.

Measured 2026-09-25 and 2026-09-26, at first-party list prices of
2026-09-25, uncached: the same whole-branch review — a 121 KB diff, about 32k
input tokens — sent to each model one to three times, at the shared `high`
(Gemini, which has no such parameter, at its own default; MiniMax accepts the
field but its effect is unestablished — so those rows are not equal-effort
comparisons). The diff carried three planted bugs and one real bug that no
test exposed:

| Model | Runs | Cost | Time | Planted bugs found | Real bug found |
|---|---|---|---|---|---|
| `gpt-6-luna` | 3 | $0.01 | 1.3 min | 8 of 9 | 3 of 3 |
| `glm-5.3-flash` | 2 | $0.01 | 4–5 min | 4 of 6 | 0 of 2 |
| `deepseek-flash` | 3 | $0.03 off-peak ($0.06 peak) | 2–3 min | 9 of 9 | 1 of 3 |
| `grok-4.3` | 3 | $0.03–0.05 | 1–1.5 min | 9 of 9 | 0 of 3 |
| `MiniMax-M3` | 1 | $0.06 | 5.1 min | 3 of 3 | 0 of 1 |
| `gpt-6.1-sol` † | 3 | $0.089–0.090 | under 1 min | 9 of 9 | 0 of 3 |
| `glm-5.3` | 2 | $0.11–0.12 | 3.7 min | 5 of 6 | 0 of 2 |
| `gpt-6-sol` | 2 | $0.11–0.12 | 1–2 min | 6 of 6 | 2 of 2 |
| `gemini-3.8-flash` | 1 | $0.14 | 1.2 min | 3 of 3 | 0 of 1 |
| `kimi-k3` | 1 | $0.25 | 5.5 min | 3 of 3 | 1 of 1 |
| `grok-4.7` | 1 | $0.34 | 9.6 min | 3 of 3 | 1 of 1 |

Reasoning-token counts vary two- to threefold between runs of the same request
(measured on DeepSeek, 2026-08-22), so read the costs as orders of magnitude.
Wrong claims matter as much as catches: `grok-4.3` asserted one nonexistent
bug in each of its three runs, and `glm-5.3-flash` twice judged a planted
bug's code correct; no other model made more than one minor wrong claim. One
diff is not a benchmark. Per-token prices: the
[skill README's model table](skills/second-opinion/README.md#model-details).

**† `gpt-6.1-sol`, measured 2026-09-29 at the shared `high` unless noted, is
not a like-for-like row with the ones above** — don't read its "0 of 3"
against `gpt-6-sol`'s "2 of 2" as a direct comparison. It ran on a
reconstructed copy of the same diff and brief; the original bake-off's
prompt file was never saved, so it had to be rebuilt from a written summary
(the prompt is now saved, so this won't recur). It was compared instead
against a same-day, same-prompt `gpt-6-sol` control (2 more runs, cost
$0.091 and $0.100, not shown as its own row): that control scored 5 of 6
planted and 1 of 2 real-bug on the reconstruction, both short of
`gpt-6-sol`'s original 6 of 6 and 2 of 2 above — so this reconstruction is a
harder prompt to *catch bugs in* for `gpt-6-sol` than the original was, even
though it costs less (a shorter reconstruction, most likely); whether it's
also harder for `gpt-6.1-sol` is unknown, since `gpt-6.1-sol` never ran the
original. On the identical reconstructed prompt at `high`, `gpt-6.1-sol`
matched or beat the control on planted-bug recall and cost, and found the
same real design gap (`--model` losing to an env override on an
explicitly-named default model) in 2 of 3 runs against the control's 1 of
2 — but at `high` it never found the one real, unplanted bug (a stale
`-request.json` surviving a refused rerun) that the control caught once.
Two further `gpt-6.1-sol` runs at `--effort xhigh` did catch that bug once
(1 of 2, matching the control's `high`-effort rate) — but cost $0.117 and
$0.135 to do it, 30–50% above the control's cost. So raising effort closes
the gap, just not for free; at matched cost and effort, `gpt-6.1-sol` is 0
for 3 on the one real bug in this dataset, which is also the strongest
signal either model produced on a 3-vs-2 (or 5-vs-4, counting the xhigh
runs) sample. **`gpt-6-sol` stays the in-depth default** (routing.md);
`gpt-6.1-sol` is documented as an available, same-price alternative
(`--model gpt-6.1-sol` or `SECOND_OPINION_OPENAI_MODEL=gpt-6.1-sol`) rather
than promoted on this evidence. Full run-by-run data, including the two
control-run costs above:
`.dev/model-value-2026-09-29.md` (maintainer's local dev notes, gitignored —
not in the published repo).

## Updates

Provider model lineups change faster than plugin releases. The shipped
defaults are verified as of 2026-09; when a provider ships a new model, point
the skill at it with an env var instead of waiting for an update:

    export SECOND_OPINION_KIMI_MODEL=...      # likewise _GEMINI_, _OPENAI_,
    export SECOND_OPINION_DEEPSEEK_MODEL=...  # _XAI_, _ZAI_, _MINIMAX_

The override is honored by the runner at launch (build mode), except where
the skill passes `--model` itself: when you name a model, and when it routes
an in-depth review to `gpt-6-sol`, which therefore ignores
`SECOND_OPINION_OPENAI_MODEL`. Effort follows
along on its own — the runner asks every backend but Gemini for
`reasoning_effort: high` unless `--effort` says otherwise, and that is keyed to
the provider, not to the model id. The override should point at a model which
takes the parameter. If it doesn't, the provider may answer 400 (the runner
reports `bad_request` naming it), or it may accept the field and ignore it.

## Documentation

- [skills/second-opinion/README.md](skills/second-opinion/README.md) — usage,
  model table, how reviews execute
- [skills/second-opinion/api-reference.md](skills/second-opinion/api-reference.md)
  — endpoints, request shapes, measured provider behavior
- [skills/second-opinion/SKILL.md](skills/second-opinion/SKILL.md) — the skill
  itself (what Claude follows)
- [skills/second-opinion/routing.md](skills/second-opinion/routing.md) — which
  backend, model and effort for which review; both skills read it
- [skills/direct/SKILL.md](skills/direct/SKILL.md) — the direct launcher:
  several providers, line-numbered files, second rounds
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pieces fit: fork, runner, the files
  a run leaves, and what survives what

## Troubleshooting

- **"`<PROVIDER>_API_KEY` not set"** — the key isn't in the environment Claude
  Code runs in; see Requirements above.
- **The review's envelope reports `failed` with an `error_class`** — the fork
  never runs a review itself, so this arrives only via
  `review-<provider>-envelope.json` (or the background task's own output),
  never as a fork reply. Deterministic
  classes (`bad_request`, `not_found`, genuine `auth`, `timeout_budget`,
  `output_cap`) mean the request itself is wrong for that backend; transient
  ones (`rate_limit`, `server_error`, `network`, `timeout`) are worth retrying.
  Details and measured provider behavior:
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
  `prompt-<provider>.txt` and `launch-<provider>.txt` and hands the command to
  the main session (`<provider>` is whichever backend the fork routed to —
  `kimi`, `openai`, etc.; filenames are provider-qualified so that two forks
  reviewing the same target for different providers never share a file). If
  the main session already launched the run, the outcome lands on disk once it
  finishes — look in the session's scratchpad directory for a
  `second-opinion-*/review-*-envelope.json` (the middle `*` is the provider),
  which says how the run ended and where its text is, with the matching
  `review-*-text.md` beside it. If
  it was never launched
  (the fork ended before the command ran, or the command was lost), the work
  is still recoverable: `prompt-<provider>.txt` and `launch-<provider>.txt`
  sit in that same directory. `launch-<provider>.txt` is the authoritative
  copy of that provider's command — run it as a background task exactly as
  written, whether or not you still have the PREPARED message.
- **"No task found with ID: second-opinion-second-opinion" (non-Anthropic
  driver only)** — this plugin targets Claude Code running on Anthropic models.
  The skill runs as a forked background task, and on a standard Anthropic driver
  its PREPARED handoff is delivered back to the main session automatically. If
  you point Claude Code at a non-Anthropic model endpoint (`ANTHROPIC_BASE_URL`,
  e.g. a Kimi/Moonshot-backed setup), that harness may not surface the forked
  skill's completion to the parent — so the main session can error trying to
  poll for it, never seeing the handoff, and nothing gets launched. The fork's
  work is still on disk: `.../second-opinion-<slug>/launch-<provider>.txt`
  holds the exact command it prepared — run it yourself as a background Bash task, and
  `review-<provider>-envelope.json` appearing in that same directory is the
  completion signal. This affects any forked
  skill under such a setup, not just this one.
- **A forked review returns a question, or `STATUS: FAILED — no target
  supplied`, instead of a review** — the forked skill found no target. Either the
  invocation's `args` never reached it (an upstream delivery failure), or they did
  and the fork missed them; the fork's transcript shows which. Either way it is
  not the runner, and nothing was sent to any backend. Re-invoke with the
  target's file path; if it keeps happening, use `/second-opinion:direct`, which
  launches the runner from the main session.
- **Sanity-check the runner itself** by running the unit tests below (no
  network, no keys needed).

## Using a partial review

A review can stop before it is finished two ways: the stream is interrupted
before the provider marks the end (a timeout, a dropped connection, or a quiet
close), or the model runs into its own output-token cap and the provider says
so. Either way real work is on disk, reported as status `partial`
in the envelope: normally N complete findings plus one cut mid-sentence. Use it
rather than discarding it:

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
  split it into smaller reviews. If the envelope's `finish_reason` says
  `length` (or `max_tokens` on Gemini), that is the backend's output cap, not a
  network problem; a shorter prompt or a different backend is the fix, and a
  re-run of the same request will stop in the same place.

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
