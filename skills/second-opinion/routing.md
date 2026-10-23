# Routing: backend, model and effort

Both skills choose from this file: the `/second-opinion` fork reads it before
it picks a backend, and `/second-opinion:direct` reads it in the main session.

## Available Backends

| Backend | Requires | Alternatives to the runner's default |
|---------|----------|--------------------------------------|
| Kimi | `MOONSHOT_API_KEY` | `kimi-k3.1-pro-highspeed`, when speed matters more than cost (faster and dearer; api-reference.md, naming traps). `kimi-k3`, the previous default, is slower and dearer |
| Gemini | `GEMINI_API_KEY` | `gemini-4-argon` (Google's flagship; paid keys only, not the free tier). Use it with `--effort high`: in a 2026-10-23 test it then found the real bug in both runs, at about $0.22 a review, and missed it in all three runs without (root README, Cost) |
| OpenAI | `OPENAI_API_KEY` | `gpt-6-sol` (in-depth review; the default `gpt-6-luna` is the quick and general-purpose check). `gpt-6.1-sol`, released 2026-09-29 at the same price, is also available but not yet the in-depth default — it missed the one real bug in a same-day bake-off (root README, Cost) |
| DeepSeek | `DEEPSEEK_API_KEY` | (none) |
| xAI | `XAI_API_KEY` | `grok-4.7` (listed, not recommended: the slowest and priciest per review tested) |
| z.AI | `ZAI_API_KEY` | `glm-5.3-flash` (listed, not recommended: in testing it judged a planted bug's code correct). A `/models` listing isn't access ([api-reference.md](api-reference.md)) |
| MiniMax | `MINIMAX_API_KEY` | `MiniMax-M3` (the previous default; twice the default's per-token price and about five times its review time in a 2026-10-23 test — root README, Cost) |

Per-provider **default models live in the runner**
(`scripts/run-request.py`, `DEFAULT_MODELS`, verified 2026-10) and are
resolved at launch: `--model` flag, else `SECOND_OPINION_<PROVIDER>_MODEL`
from the environment, else the built-in default. So pass `--model` in exactly
two cases: the user named a model — a built-in default included, since the
flag is what keeps an env override from replacing the model they named — or
the routing row you chose names a model that is not that provider's runner
default (today only `gpt-6-sol`). Otherwise omit it. An override env var
needs no special handling for effort: the runner's default is keyed to the
provider, not to the model id, so an overridden model gets the same `high`.

**Default backend: OpenAI.** Its runner default, `gpt-6-luna`, is the quick
and general-purpose check; an in-depth review goes to `gpt-6-sol` (see the
routing table). Use another backend when the user asks or for an additional
independent perspective — seven families means up to seven independent
opinions. If the chosen backend's key is missing, the runner reports it as a
`usage_error` seconds after launch, and the main session can relaunch on
another backend.

## Routing guidance

| Situation | Prefer |
|-----------|--------|
| Quick or general-purpose check (default) | OpenAI (runner default `gpt-6-luna`) |
| In-depth review: the user asks for a thorough or in-depth review, or the target is a spec, design, implementation plan, whole-branch or pre-merge diff, completed implementation, or debugging that is stuck | OpenAI `--model gpt-6-sol`. For a second in-depth opinion, Kimi, and z.AI third — but for a spec or document, z.AI second and Kimi third (the maintainer's ranking). The default `high` covers depth; go higher only for the hardest problems (see Effort) |
| Fast feedback | OpenAI (its default `gpt-6-luna`), then Gemini |
| Cheap feedback | OpenAI (its default `gpt-6-luna`), DeepSeek, MiniMax, or xAI. xAI's default `grok-4.3` is cheap and fast, but check what it reports: in testing it asserted bugs that were not there. Kimi is not a cheap check |
| File-heavy or long documents | Any default (each takes ~1M tokens; past a threshold the price rises: xAI past 200k, and OpenAI's GPT-6 models bill 2x input and 1.5x output past 272k) |
| Another independent opinion | Any unused family — different family, different blind spots |
| No OpenAI/Kimi credits | Gemini (free tier) or DeepSeek (near-free) |

Apply the table in this order. (1) A provider or model the user names wins;
so does an explicit ask for a quick, fast or cheap check. (2) Otherwise the
in-depth row applies when its trigger matches; when unsure, the request is
not in-depth, and the default quick check applies. (3) "Second" and "third"
in-depth opinions count the external in-depth reviews of the same target
that the request names as done ("OpenAI already reviewed"), or the count it
asks for ("a third opinion"): with none, the review goes to `gpt-6-sol`,
even when the user says "a second opinion" (the skill's name, not a count).
(4) The long-documents row only adjusts cost; it never replaces the route
chosen above.

The table says what a review would use. It does not record what an earlier
review used.

## Effort

The runner sends `reasoning_effort: high` to every backend but gemini, so
**omit `--effort`** and the review runs at that shared level whichever of
them you picked. Pass **`--effort low`** only when the user wanted a quick or
cheap check. Gemini is the exception: without `--effort` it gets no
thinking level and decides for itself, which keeps it fast and cheap for
its "fast feedback" role. For an in-depth Gemini review, pass `--effort
high`, which it receives as its thinking level; in a 2026-10-23 test that is what let `gemini-4-argon` find a real
bug it otherwise missed. Higher than `high`
(`xhigh` on OpenAI / xAI / MiniMax, `max` on kimi / DeepSeek / z.AI /
MiniMax) is for genuinely hard problems and only where the backend offers
it; gemini stops at `high`, and the runner refuses `xhigh`
and `max` for it. Never use `medium` as a middle ground: z.AI rejects it,
and kimi and DeepSeek return 200 for it but do not document it.
