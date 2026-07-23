# second-opinion

A [Claude Code](https://claude.com/claude-code) plugin that gets a second
opinion on Claude's work from an external model — Kimi, Gemini, OpenAI,
DeepSeek, or xAI — via their REST APIs. Reviews code, plans, drafts,
arguments, or any other work product; Claude reads the review and remains the
decision-maker.

    /second-opinion is this refactoring approach sound?
    /second-opinion ask DeepSeek to review this draft
    /second-opinion with Gemini 2.5-pro: review all the files in this dir

Claude also invokes it proactively when a plan or piece of work is worth an
outside check.

## ⚠️ Where your content goes

**The content you ask to have reviewed is sent to the third-party provider you
route to** (Moonshot AI, Google, OpenAI, DeepSeek, or xAI), under that
provider's API data terms. Nothing leaves your machine until the skill runs,
and each request goes to exactly one backend — but do not route confidential
material to a provider you wouldn't paste it into directly, and check the
provider's data-retention/training policy if that matters for your content.

## Install

From the [ai4phi marketplace](https://github.com/AI-4-Phi/plugins):

    /plugin marketplace add AI-4-Phi/plugins
    /plugin install second-opinion@ai4phi

## Requirements

- `python3` — the runner is stdlib-only: no packages, no venv.
- An API key, exported in your environment, for each backend you want (any
  subset works; the skill falls back across configured backends):

| Backend | Env var | Get a key |
|---|---|---|
| Kimi (default) | `MOONSHOT_API_KEY` | [platform.kimi.ai](https://platform.kimi.ai/) |
| Gemini | `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) (free tier covers `gemini-2.5-pro`) |
| OpenAI | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com/api-keys) |
| DeepSeek | `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| xAI | `XAI_API_KEY` | [console.x.ai](https://console.x.ai/) |

## Cost

Each review is one API call to the chosen provider, billed to your key. Rough
per-review order of magnitude (2026-07 prices, a typical few-thousand-token
review): Kimi `kimi-k3` is the priciest ($3/M input, $15/M output — usually
cents per review); DeepSeek and Gemini Flash are near-free; Gemini
`gemini-2.5-pro` has a free tier. Large documents at high reasoning effort
cost proportionally more — the skill warns and routes those explicitly.

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

## Development

Unit tests for the runner (gate, error classification, envelope contract):

    python3 -m unittest discover -s tests -v

## License

[MIT](LICENSE)
