# Second Opinion Skill

A Claude Code skill that gets feedback from external models (Kimi, Gemini,
OpenAI, DeepSeek, xAI, GLM/z.AI, or MiniMax) via their REST APIs on code,
plans, writing, or any work product.

## Usage

    /second-opinion [file path and question]

Name the file (or a saved diff): the skill runs in a fork that cannot see the
conversation. The skill defaults to OpenAI: `gpt-6-luna` for quick and general-purpose
checks, and `gpt-6-sol` for an in-depth review (a spec, plan, pre-merge diff or
completed implementation, or whenever you ask for depth). To use another
backend, mention it:

    /second-opinion in depth: review docs/plan.md
    /second-opinion using Kimi: is the refactoring in src/parser.py sound?
    /second-opinion ask DeepSeek to review drafts/intro.md
    /second-opinion with Gemini: review all the files in this dir

## How it executes

The skill always *prepares* a review — it never runs one itself. It writes the
composed prompt to `prompt.txt` and the exact `scripts/run-request.py` launch
command to `launch.txt` in a scratch work directory, then returns
`STATUS: PREPARED` with that command. This is by design, not a fallback: every
review takes this path, regardless of size or reasoning effort — there is no
synchronous shortcut.

The main session launches the returned command as a background task. The
review then runs as a plain background process, outside the skill — the fork
that prepared it has already ended by the time the review finishes, so it
cannot report back. The envelope file (`review-envelope.json`) appearing in
the work directory is the completion signal: its appearance is what the main
session watches for, and Claude reads the review from disk once it's there.
The skill does not paste the review back through the fork or summarize it,
because a summary of a technical review loses the specific objections that
make it worth having. The fork itself runs on Sonnet regardless of your
session's model — it only does plumbing, and the review's quality comes from
the backend you route to, not from it.

Responses stream, which mostly matters when something goes wrong. A review cut
short — by a timeout, or by the backend's own output-token cap — still leaves
everything it had written on disk, reported as status `partial` in the envelope
— see the root README's ["Using a partial
review"](../../README.md#using-a-partial-review) for how to act on one.

The runner (`scripts/run-request.py`, stdlib Python — no dependencies) prints a
single JSON envelope describing the outcome (`completed`/`partial`/`failed`/
`usage_error`) so the agent gets a typed result, and it classifies errors:
deterministic failures (bad model, genuine auth error, malformed request) fail
fast, while transient ones (rate limits, 5xx, network, empty bodies, OpenAI's
flaky 401) are retried — an empty body the provider blames on its own
output-token cap is the exception, and fails once.

## Where your content goes

**Whatever you ask for a second opinion on — code, diffs, drafts, documents —
is sent to the third-party provider you route to** (Moonshot, Google, OpenAI,
DeepSeek, xAI, Z.AI, or MiniMax), under that provider's API data terms. Nothing is sent
anywhere until you invoke the skill, and only to the one backend chosen for
that request. Don't route confidential material to a provider you wouldn't
paste it into directly, and check your provider's data-retention/training
policy if that matters for your content.

## Model details

Verified 2026-09-25 (`grok-4.3`: 2026-09-26): each model is listed by its
provider's `/models` and answered a live completion at the shared `high`
(Gemini, which has no such parameter, at its own default). "Best for" follows
the maintainer's ranking, informed by the measured reviews in the root
README's Cost section.
Prices are first-party list prices in USD per million tokens, uncached input /
output, read 2026-09-25. They change, so check the provider's page before
you rely on one. Models churn faster than skill releases — see "Changing
default models" below to adapt without waiting for one. "(default)" marks
each provider's default model; the skill's default backend is OpenAI. What a
whole review costs: the root README's [Cost](../../README.md#cost) section.

| Backend | Model | Best for | $/M in / out | Notes |
|---------|-------|----------|--------------|-------|
| Kimi | `kimi-k3` (default) | Second in-depth opinion (third for specs and docs) | $3.00 / $15.00 | 1M ctx; always-on thinking; slow |
| OpenAI | `gpt-6-luna` (default) | Quick and general-purpose checks; first pick for a fast review | $0.10 / $0.50 | 1.05M ctx; its predecessor was tier-gated on some keys — if yours is refused, set `SECOND_OPINION_OPENAI_MODEL=gpt-6-sol` |
| OpenAI | `gpt-6-sol` | In-depth review, first pick | $2.00 / $10.00 | 1.05M ctx |
| DeepSeek | `deepseek-flash` (default) | Cheap independent opinion | $0.15 / $0.60 off-peak, $0.30 / $1.20 peak | 1M ctx; peak is 01–04 and 06–10 UTC on weekdays |
| xAI | `grok-4.3` (default) | Cheap, fast opinion — check its findings | $1.25 / $2.50 up to 200k, $2.50 / $5.00 above | 1M ctx; reported bugs that were not there (root README, Cost) |
| xAI | `grok-4.7` | Not recommended: slow and expensive | $2.00 / $6.00 up to 200k, $4.00 / $12.00 above | 500k ctx |
| z.AI | `glm-5.3` (default) | Second in-depth opinion for specs and docs (the maintainer's pick), third otherwise | $1.40 / $4.40 | 1M ctx |
| z.AI | `glm-5.3-flash` | Not recommended for reviews | $0.15 / $0.50 | 1M ctx; judged a planted bug's code correct (root README, Cost) |
| MiniMax | `MiniMax-M3` (default) | Cheap independent opinion | $0.30 / $1.20 | 1M ctx; price doubles above 512k input tokens |
| Gemini | `gemini-3.8-flash` (default) | Fast review, second pick | $0.75 / $3.75 until 2026-12-31, then $1.50 / $7.50 | 1M ctx; free tier per Google's pricing page (read 2026-09-25) |

Kimi has the highest per-token price of the defaults and is among the slowest
(always reasoning); reserve it for in-depth work. For a quick or cheap check
use the OpenAI default (`gpt-6-luna`), DeepSeek's default, or xAI's default.

**Reasoning level.** Every backend but Gemini is asked for
`reasoning_effort: high`, so each gets the same requested level whichever one you route to —
`high` is the highest level all of them accept (`xhigh` and `max` are not
offered everywhere, and `kimi-k3` and `glm-5.3` have no `medium`). Pass `--effort low` for a quick check. Because `high` is a
long-path level, a run that does not pass `--effort` must also pass `--long`;
the skill's own launch command always does.

Naming traps and API details: see [api-reference.md](api-reference.md).

## Changing default models

When a provider ships a new model, set an env var instead of editing the skill:

    export SECOND_OPINION_KIMI_MODEL=...      # likewise _GEMINI_, _OPENAI_,
    export SECOND_OPINION_DEEPSEEK_MODEL=...  # _XAI_, _ZAI_, _MINIMAX_

The override is honored by the runner at launch, in build mode — not by the
skill. When the skill composes a launch command it adds `--model` only when
you named a model (a built-in default included, so your named model wins over
an env override) or when it routes an in-depth review to `gpt-6-sol`, which
therefore ignores `SECOND_OPINION_OPENAI_MODEL`. Otherwise an env-var override
takes effect on its own, with no `--model` flag needed. Effort needs no special
handling: the runner's default is keyed to the provider, not to the model id,
so an overridden model gets the same `reasoning_effort: high`. The one thing to
know is that the override should point at a model that *takes* that
parameter. If it doesn't, the provider may answer 400 (the runner reports
`bad_request` naming it), or it may accept the field and ignore it —
`kimi-k2.7-code` does, so an override to it runs at the model's own default.
Details: [api-reference.md](api-reference.md#model-and-effort-resolution-build-mode).

## Requirements

`python3` (stdlib only — no packages, no venv), plus an API key for each
backend you want, exported in your environment (e.g. from your shell profile
or a secrets file it sources). You only need keys for the backends you use:

- **Kimi:** `MOONSHOT_API_KEY` ([platform.kimi.ai](https://platform.kimi.ai/))
- **Gemini:** `GEMINI_API_KEY` ([Google AI Studio](https://aistudio.google.com/apikey); free tier: see the model table)
- **OpenAI:** `OPENAI_API_KEY` ([platform.openai.com](https://platform.openai.com/api-keys))
- **DeepSeek:** `DEEPSEEK_API_KEY` ([platform.deepseek.com](https://platform.deepseek.com/api_keys))
- **xAI:** `XAI_API_KEY` ([console.x.ai](https://console.x.ai/))
- **z.AI:** `ZAI_API_KEY` ([docs.z.ai](https://docs.z.ai/))
- **MiniMax:** `MINIMAX_API_KEY` ([platform.minimax.io](https://platform.minimax.io/))
