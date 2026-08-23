# Second Opinion Skill

A Claude Code skill that gets feedback from external models (Kimi, Gemini,
OpenAI, DeepSeek, xAI, GLM/z.AI, or MiniMax) via their REST APIs on code,
plans, writing, or any work product.

## Usage

    /second-opinion [question or topic]

The skill defaults to Kimi (`kimi-k3`). To use another backend, mention it:

    /second-opinion using OpenAI: is this refactoring approach sound?
    /second-opinion ask DeepSeek to review this draft
    /second-opinion from Grok: review these changes
    /second-opinion with Gemini 2.5-pro: review all the files in this dir

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

Verified 2026-07. Models churn faster than skill releases — see "Changing
default models" below to adapt without waiting for one.

| Backend | Model | Best for | Notes |
|---------|-------|----------|-------|
| Kimi | `kimi-k3` (default) | Deep general + reasoning review | 1M ctx; always-on thinking; priciest ($3/$15 per M) |
| Gemini | `gemini-3.1-pro-preview` | Deepest Gemini review | Thinking model, preview-only tier |
| Gemini | `gemini-2.5-pro` | Large context / bulk review | 1M tokens, GA/stable, free tier |
| Gemini | `gemini-3.5-flash` | Fast feedback | Lower latency |
| OpenAI | `gpt-5.6-sol` | Deepest OpenAI analytical review | Flagship; the shared `high` default suits hard problems |
| OpenAI | `gpt-5.6-terra` | Balanced everyday review | ~gpt-5.5-level at half price |
| OpenAI | `gpt-5.5` | Prior OpenAI flagship | Still strong |
| DeepSeek | `deepseek-v4-pro` | Independent opinion, cheap deep review | 1M ctx; `reasoning_effort` up to `xhigh`; $1.32/M in (2026-08) |
| DeepSeek | `deepseek-v4-flash` | Cheapest useful review | 1M ctx; $0.44/M in (2026-08) |
| xAI | `grok-4.5` | Independent opinion, flagship | 500k ctx; $2/$6 per M |
| xAI | `grok-4.3` | Long documents | 1M ctx; ~half the price of 4.5 |
| z.AI | `glm-5.3` | Independent opinion | Reasons by default; glm-5.x moves fast, but a `/models` listing isn't access — see api-reference.md |
| MiniMax | `MiniMax-M3` | Fast independent opinion | Reasons by default; ~5 s on small prompts |

Kimi is the default but the priciest and slowest (always reasoning); for a quick
or cheap check reach for `deepseek-v4-flash` or `gemini-3.5-flash` instead.

**Reasoning level.** Every backend but Gemini is asked for
`reasoning_effort: high`, so depth is the same whichever one you route to —
`high` is the only level all of them accept (`kimi-k3` and `glm-5.3` have no
`medium`). Pass `--effort low` for a quick check. Because `high` is a
long-path level, a run that does not pass `--effort` must also pass `--long`;
the skill's own launch command always does.

Naming traps and API details: see [api-reference.md](api-reference.md).

## Changing default models

When a provider ships a new model, set an env var instead of editing the skill:

    export SECOND_OPINION_KIMI_MODEL=...      # likewise _GEMINI_, _OPENAI_,
    export SECOND_OPINION_DEEPSEEK_MODEL=...  # _XAI_, _ZAI_, _MINIMAX_

The override is honored by the runner at launch, in build mode — not by the
skill. When the skill composes a launch command it only ever adds `--model`
if the user asked for a specific non-default model; an env-var override takes
effect on its own, with no `--model` flag needed. Effort needs no special
handling: the runner's default is keyed to the provider, not to the model id,
so an overridden model gets the same `reasoning_effort: high`. The one thing to
know is that the override must point at a model that *takes* that parameter —
if it doesn't, the provider answers 400 and the runner reports `bad_request`
naming it.
Details: [api-reference.md](api-reference.md#model-and-effort-resolution-build-mode).

## Requirements

`python3` (stdlib only — no packages, no venv), plus an API key for each
backend you want, exported in your environment (e.g. from your shell profile
or a secrets file it sources). You only need keys for the backends you use:

- **Kimi:** `MOONSHOT_API_KEY` ([platform.kimi.ai](https://platform.kimi.ai/))
- **Gemini:** `GEMINI_API_KEY` ([Google AI Studio](https://aistudio.google.com/apikey); free tier covers gemini-2.5-pro)
- **OpenAI:** `OPENAI_API_KEY` ([platform.openai.com](https://platform.openai.com/api-keys))
- **DeepSeek:** `DEEPSEEK_API_KEY` ([platform.deepseek.com](https://platform.deepseek.com/api_keys))
- **xAI:** `XAI_API_KEY` ([console.x.ai](https://console.x.ai/))
- **z.AI:** `ZAI_API_KEY` ([docs.z.ai](https://docs.z.ai/))
- **MiniMax:** `MINIMAX_API_KEY` ([platform.minimax.io](https://platform.minimax.io/))
