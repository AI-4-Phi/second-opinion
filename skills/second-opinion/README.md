# Second Opinion Skill

A Claude Code skill that gets feedback from external models (Kimi, Gemini,
OpenAI, DeepSeek, or xAI) via their REST APIs on code, plans, writing, or any
work product.

## Usage

    /second-opinion [question or topic]

The skill defaults to Kimi (`kimi-k3`). To use another backend, mention it:

    /second-opinion using OpenAI: is this refactoring approach sound?
    /second-opinion ask DeepSeek to review this draft
    /second-opinion from Grok: review these changes
    /second-opinion with Gemini 2.5-pro: review all the files in this dir

## How it executes (short vs long reviews)

Small requests run synchronously and hand back the finished review's file path.
Large requests (32 KB+ prompt) or deep-reasoning requests (`reasoning_effort:
high`/`xhigh`/`max`) take longer than a forked skill can survive, so the skill
only *prepares* them: it returns `STATUS: NOT-RUN` plus the exact
`scripts/run-request.py` command for the main session to run in the background.
This is by design — a "NOT-RUN" reply is the skill working correctly, not
failing.

Either way the review lands on disk and Claude reads it from there; the skill
does not paste it back through the fork or summarize it, because a summary of a
technical review loses the specific objections that make it worth having. The
fork itself runs on Sonnet regardless of your session's model — it only does
plumbing, and the review's quality comes from the backend you route to, not
from it.

Responses stream, which mostly matters when something goes wrong. A review cut
short by a timeout still leaves everything it had written on disk, reported as
`STATUS: PARTIAL` — the completed findings are valid and Claude will act on
them, ignoring any final finding that stops mid-sentence. If it looks like more
was coming, the right move is to fix what you already know about and *then* ask
again, so the next review sees the corrected version instead of repeating
itself.

The runner (`scripts/run-request.py`, stdlib Python — no dependencies) prints a
single JSON envelope describing the outcome (`completed`/`failed`/`usage_error`)
so the agent gets a typed result, and it classifies errors: deterministic
failures (bad model, genuine auth error, malformed request) fail fast, while
transient ones (rate limits, 5xx, network, empty bodies, OpenAI's flaky 401) are
retried.

## Where your content goes

**Whatever you ask for a second opinion on — code, diffs, drafts, documents —
is sent to the third-party provider you route to** (Moonshot, Google, OpenAI,
DeepSeek, or xAI), under that provider's API data terms. Nothing is sent
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
| OpenAI | `gpt-5.6-sol` | Deepest OpenAI analytical review | `reasoning_effort: high` for hard problems |
| OpenAI | `gpt-5.6-terra` | Balanced everyday review | ~gpt-5.5-level at half price |
| OpenAI | `gpt-5.5` | Prior OpenAI flagship | Still strong |
| DeepSeek | `deepseek-v4-pro` | Independent opinion, cheap deep review | 1M ctx; `reasoning_effort` up to `xhigh`; ~$0.44/M in |
| DeepSeek | `deepseek-v4-flash` | Cheapest useful review | 1M ctx; ~$0.14/M in |
| xAI | `grok-4.5` | Independent opinion, flagship | 500k ctx; $2/$6 per M |
| xAI | `grok-4.3` | Long documents | 1M ctx; ~half the price of 4.5 |

Kimi is the default but the priciest and slowest (always reasoning); for a quick
or cheap check reach for `deepseek-v4-flash` or `gemini-3.5-flash` instead.

Naming traps and API details: see [api-reference.md](api-reference.md).

## Changing default models

When a provider ships a new model, set an env var instead of editing the skill:

    export SECOND_OPINION_KIMI_MODEL=...      # likewise _GEMINI_, _OPENAI_,
    export SECOND_OPINION_DEEPSEEK_MODEL=...  # _XAI_

The skill uses that value as the backend's default model. One caveat: the
runner's protection against accidental max-effort runs knows only the models in
the table above, so with an override in place requests should always set
`reasoning_effort` explicitly (the skill does this for Kimi already).

## Requirements

`python3` (stdlib only — no packages, no venv), plus an API key for each
backend you want, exported in your environment (e.g. from your shell profile
or a secrets file it sources). You only need keys for the backends you use:

- **Kimi:** `MOONSHOT_API_KEY` ([platform.kimi.ai](https://platform.kimi.ai/))
- **Gemini:** `GEMINI_API_KEY` ([Google AI Studio](https://aistudio.google.com/apikey); free tier covers gemini-2.5-pro)
- **OpenAI:** `OPENAI_API_KEY` ([platform.openai.com](https://platform.openai.com/api-keys))
- **DeepSeek:** `DEEPSEEK_API_KEY` ([platform.deepseek.com](https://platform.deepseek.com/api_keys))
- **xAI:** `XAI_API_KEY` ([console.x.ai](https://console.x.ai/))
