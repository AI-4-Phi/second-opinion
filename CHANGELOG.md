# Changelog

## Unreleased

- **A stream that closes without an end marker is `partial`, not
  `completed`.** The runner took a quiet EOF after some text as a finished
  review, so a stream the provider closed early could pass as complete. A
  clean end now needs `[DONE]` or a finish reason; text followed by neither
  is reported as `partial` (exit 3) with a `detail` naming the missing
  marker. With no text the run is `empty` or `output_cap`, as before. A live
  probe of all seven backends (2026-09-26) found every one sent a finish
  reason on a clean end, while minimax and gemini sent no `[DONE]`, so no
  backend needs an exception; all seven then completed through the changed
  runner. api-reference.md no longer says every OpenAI-compatible stream
  ends with `[DONE]`.
- **A stream that breaks after its finish reason is `completed`.** The
  reason arrives with the last text or after it, so the break costs only the
  usage totals; it used to be reported `partial`, which tells the reader to
  discard a finding that was whole. A cap reason still means `partial`, as
  does text arriving after the reason (no probed backend sends any), and a
  cap with no text is `output_cap` rather than a retried `empty`. Skipped
  undecodable `data:` lines are now counted in the log.
- **Streamed gemini output reads candidate 0 only**, as the non-streaming
  path and the finish-reason check already did. Build mode never asks for
  more than one candidate, so its reviews do not change.
- Reviewed by gpt-6-sol and Kimi, then z.AI on the fixes.

## 0.5.0 — 2026-09

- **New skill: `/second-opinion:direct`.** It runs in the main session, not
  a fork: the session writes the prompt itself, adding files with the shell
  (`cat -n`, so reviewers can cite real line numbers), and launches the
  runner once per provider on that one prompt file. Use it for several
  providers on one prompt, a second round that carries the first round's
  findings and declines, or a prompt already written. It finds the runner
  from the harness's "Base directory for this skill" line, creates its work
  directory with `mkdir` (no `-p`) so two direct sessions cannot share one, and
  holds the same closed four-part prompt as the fork, with an explicit
  warning that the main session sees private context the fork does not.
  Facts stay in `api-reference.md` and the fork's routing sections.
- **The fork's FAILED message names no runner path.** It retyped one, and on
  2026-09-26 one FAILED message misspelled the home directory and another
  left `<skill-dir>` unresolved. FAILED now says to re-invoke with the file
  path, then to use `/second-opinion:direct`. The root README's
  troubleshooting recipe is replaced by the same pointer.
- Reviewed before release by gpt-6-sol and Kimi, then z.AI on the fixes; the
  z.AI round caught a launch command that relied on a shell variable set in
  an earlier Bash call (each call starts a fresh shell). Tested end to end:
  the skill launched gpt-6-sol and Kimi in parallel on one prompt file.

## 0.4.2 — 2026-09

- **The review prompt no longer carries unrequested session context.** A
  fork sees the session's instructions, CLAUDE.md files, CLAUDE.local.md and
  memory index. Asked to review a project's CLAUDE.md, one fork appended
  that project's private CLAUDE.local.md "for reference" to a prompt bound
  for an outside provider (caught before launch). Prompt Construction now
  states the prompt's parts: the work, the target from step 1, earlier
  reviews, the questions, and nothing else.
- **Earlier reviews are described as the request states them.** Asked for a
  "second in-depth opinion; OpenAI already reviewed", forks told the
  reviewer the earlier review used `gpt-6-sol` at high effort (2 of 4
  runs), reading the routing table as a record of what a past review used.
- **PREPARED no longer leaves `<WORKDIR>` placeholders.** The informational
  "outputs:" and cancel lines now name their files as next to `prompt.txt`,
  so only the prompt line and the launch command carry the work directory.
  Before: 4 of 9 forks left a literal `<WORKDIR>`.
- **The request now sits on one Request line at the top of SKILL.md.**
  `$ARGUMENTS` appeared four times, and the harness substitutes every one,
  so two rules read as nonsense once filled in: "Empty `<request>` in a fork
  is an upstream delivery failure" and "no <request> reached this fork". 2 of
  7 forks on the first 0.4.2 text returned `FAILED — no target supplied`
  although the request had arrived. It now appears once; step 1, "When to
  Use" and the FAILED template refer to that line. The root README's
  troubleshooting no longer calls every no-target FAILED a delivery failure.
- **The fork no longer relies on the conversation, which it cannot see.**
  Verified 2026-09-26 for both paths: a fork started by the Skill tool and
  one started by a typed `/second-opinion` each failed to find a marker
  placed only in the conversation. Yet step 1 allowed a target "from
  unambiguous context", routing rule 3 counted reviews "you can see in this
  conversation", and Prompt Construction part 3 cited "this conversation".
  All three now use the request alone; a request that points back into the
  conversation ("the plan we discussed") gets FAILED. The frontmatter
  description, the only skill text the main session sees, now says to put
  the target's path and any earlier reviews in the args, and both READMEs'
  usage examples name a file ("review this draft" gave a fork nothing to
  find). ARCHITECTURE.md states what a fork sees. Part 3 is now a copy rule:
  quote the request's words about earlier reviews and add nothing.
- Verified 2026-09-26 on the final text: 5 of 5 forks on the root README
  prepared; six more forks routed a second in-depth opinion to Kimi (code)
  and z.AI (document), sent an in-depth review with no earlier one to
  `gpt-6-sol`, and failed "the plan we just discussed". Across 11 forks with the new prompt rules, none left a
  placeholder or added unrequested context; 1 still gave the earlier OpenAI
  review a model (`gpt-6-sol`), down from 2 of 4.

## 0.4.1 — 2026-09

- **Two requests on one target no longer share a work directory.** SKILL.md
  step 4 found a fresh WORKDIR with Glob, but Claude Code builds with
  embedded search (2.1.283 seen) have no Glob or Grep tool, and the fork has
  no shell. So a second request with the same slug, the usual in-depth review
  followed by a second in-depth opinion, reused the first one's directory:
  it overwrote `prompt.txt` and `launch.txt`, and its launch command's
  `rm -f` deleted the first review. Step 4 now probes each candidate
  (`second-opinion-<slug>`, then `-2`, `-3`, …) by Reading its `prompt.txt`
  with `limit: 1`, which works in every build. Verified 2026-09-26 with forks
  on one target landing in `-2`, then `-3`, each earlier directory untouched.
  The probe does not cover two forks preparing on the same target at the
  same moment: prepare those one after the other.
- SKILL.md and ARCHITECTURE.md now list the fork's tools as Read and Write,
  plus Glob and Grep in builds that have them.

## 0.4.0 — 2026-09

- **The default backend is now OpenAI, not Kimi, in two tiers.** Its runner
  default `gpt-6-luna` does quick and general-purpose checks; SKILL.md routes
  an in-depth review (a spec, design, plan, pre-merge diff, completed
  implementation, stuck debugging, or any request for depth) to `gpt-6-sol`
  with an explicit `--model`, then Kimi and z.AI `glm-5.3` for further
  in-depth opinions (`glm-5.3` ahead of Kimi for specs and docs). SKILL.md now states the order its routing
  rules apply in: a model, provider or speed the user names wins; an unsure
  case is a quick check, not an in-depth one. On a seeded whole-branch review (the 0.2.0 diff,
  121 KB, three planted bugs plus one real bug no test exposed), both
  `gpt-6-luna`, at about a cent a run, and `gpt-6-sol` found the real bug in
  every run (counts: the root README's Cost section).
- **New per-provider defaults, verified 2026-09-25** (`grok-4.3`: 2026-09-26)
  by `GET /models` and a live completion (at the shared `high`; Gemini at its
  own default): OpenAI `gpt-6-luna` (was `gpt-5.6-sol`), DeepSeek
  `deepseek-flash` (V4.1-Flash), xAI `grok-4.3` (was `grok-4.5`), Gemini
  `gemini-3.8-flash` (was `gemini-3.1-pro-preview`; its introductory price
  doubles on 2027-01-01). Kimi `kimi-k3`, z.AI `glm-5.3` and MiniMax
  `MiniMax-M3` are unchanged.
- **Listed but not recommended:** `grok-4.7` (slowest and dearest per review
  tested) and `glm-5.3-flash` (it judged a planted bug's code correct).
  `grok-4.3` is recommended as a cheap option with a caveat: it asserted
  bugs that were not there. A fast review goes
  to `gpt-6-luna`, then Gemini.
- **Rows dropped:** `deepseek-v4-pro` (same findings as `deepseek-flash` at
  four times the cost) and `gemini-3.1-pro-preview` (most expensive per finding),
  plus the superseded `gpt-5.6-terra`, `gpt-5.5`, `gemini-2.5-pro`, `gemini-3.5-flash` and
  `MiniMax-M2.7-highspeed`. `gpt-6-astra` was evaluated and not listed
  (unmeasured, about five times `gpt-6-sol`'s price).
- **`--model` now travels whenever the user names a model**, a built-in
  default included. Before, the skill dropped the flag for a named default,
  so a `SECOND_OPINION_<PROVIDER>_MODEL` override silently replaced the model
  the user asked for.
- **Prices and per-review costs, one home each.** Per-token prices (first-party,
  read 2026-09-25) live in the skill README's model table; the measured cost,
  time and bug catches of the seeded review live in the root README's Cost
  section.
- **DeepSeek renamed and re-tiered.** `deepseek-v4-flash` was retired on
  2026-09-10; the id still answers but `deepseek-flash` serves it. DeepSeek
  now documents `low`/`high`/`max` with an unset default of `high`; `medium`
  and `xhigh` still return 200.
- **The gate set is renamed `HIGH_EFFORT_BY_DEFAULT`** (was
  `TOP_EFFORT_BY_DEFAULT`): DeepSeek's unset default is now `high`, not its top
  tier, so the old name and the refusal message ("reasons at its top tier")
  were false. `deepseek-flash` replaces `deepseek-v4-flash`, and `grok-4.7`
  joins on the strength of xAI's `/models` reporting
  `default_reasoning_effort: "high"`; `grok-4.3` reports `"low"` and stays
  out. Legacy mode only; build mode always resolves an effort.
- **xAI's accepted effort levels are now verified:** `grok-4.7` takes `low`,
  `medium`, `high`, `xhigh`; `grok-4.3` also takes `none`. The OpenAI GPT-6
  sets are measured too (`none`–`xhigh` on sol/luna, no `max`).
- **Docs no longer promise a 400 for an override without
  `reasoning_effort`.** `kimi-k2.7-code` accepts the field at every level and
  ignores it; on the 121 KB diff it hit its output-token cap before any
  review text arrived (`output_cap`). It is listed as a naming
  trap, not an alternative.

## 0.3.1 — 2026-08

- **SKILL.md's numbered steps caught up with the shared default.** 0.3.0
  replaced the per-provider effort rule but left step 3 saying "choose backend
  and effort from the routing tables" and step 5 saying the emitted command
  carries `--effort` "per step 3's provider rule" — a rule that no longer
  existed, so a fork working through the steps was sent looking for guidance
  the prose above had deleted. Step 3 now says to add `--effort` only when
  departing from the shared `high`, and step 5 matches. Text the fork reads at
  runtime, hence its own release rather than a docs commit.

## 0.3.0 — 2026-08

- **One reasoning level for every backend: `reasoning_effort: high`.** Omit
  `--effort` and the runner now sends `high` to Kimi, OpenAI, DeepSeek, xAI,
  z.AI and MiniMax alike, instead of leaving each request wherever that
  vendor's own default happened to sit — which ranged from OpenAI's middle tier
  to Kimi's `max`. Review depth is now a property of the skill, not of the
  route. `--effort low` is the quick-check opt-out; `xhigh`/`max` still work
  where the backend offers them.
- **`high` because it is the only level everyone accepts.** `kimi-k3` and
  `glm-5.3` both reject `medium`, so there is no shared middle; `xhigh` and
  `max` are not offered everywhere. A per-provider mapping would have been a
  decay-prone tier table, which this runner deliberately does not keep — the
  provider's own 400 stays the authority on validity.
- **The default is gate-blocking, on purpose.** `high` is one of the gate's
  refusal conditions, so a build-mode call that passes no `--effort` is refused
  in the foreground unless it also passes `--long`. The default genuinely is a
  5–30 minute request on a large input, and the gate exists to stop exactly
  that from starting in a tool call that dies at 10 minutes and orphans the
  runner. The skill's launch command always passes `--long`; a direct caller
  who wants a foreground run passes `--effort low`.
- **The injection is now provider-keyed, reversing 0.2.4's model-keyed rule.**
  That rule was right for what the injection *was* — a protection that forced
  `"low"` on models known to reason at their top tier, which is meaningless for
  a model whose default you do not know. This is a policy instead ("ask every
  backend for the same level"), and a policy has no such prerequisite, so it
  covers a model reached through `SECOND_OPINION_<PROVIDER>_MODEL` too. If that
  model has no `reasoning_effort`, the provider answers 400 and the runner
  reports `bad_request` naming it — loud and one flag from fixed.
- **z.AI and MiniMax now get an effort too** (they were skipped as "support
  unverified" since 2026-07-23). Verified 2026-08-23: `glm-5.3` accepts `low`,
  `high`, `max` and nothing else — `medium` and `xhigh` each return a
  synchronous 400, error 1210, whose message names the valid set outright.
  `MiniMax-M3` returns 200 for every level; whether it acts on the value is not
  established, and sending the shared default is harmless either way.
- `TOP_EFFORT_BY_DEFAULT` stays, unchanged and gate-only: with build mode
  always resolving an effort, it now fires solely on a legacy hand-built body
  that omits the field. `glm-5.3` is deliberately **not** added — its unset
  default is still unknown, and that set takes positive evidence only.
- Verified end to end through the runner 2026-08-23: Kimi, OpenAI, z.AI and
  MiniMax each sent `"high"` and completed, Gemini sent no such field and
  completed. xAI was not re-probed. 150 tests pass.

## 0.2.4 — 2026-08

- **The gate no longer waves through an unset DeepSeek effort.** It already
  refused a foreground `reasoning_effort` of `high`/`xhigh`/`max`, and it
  already refused a `kimi-k3` body with the field absent — but on both DeepSeek
  v4 models an *omitted* field is wire-identical to `xhigh` (measured
  2026-08-22: `medium`/`high`/`xhigh` and an omitted field all bill the same
  constant 79-token server-side prompt injection; only `low` opts out —
  re-confirmed through the runner 2026-08-23 at 35 prompt tokens against 114),
  and that request sailed past. `deepseek-v4-pro` and `deepseek-v4-flash` now
  join `kimi-k3` in the set, so an unset effort blocks the same way the
  spelled-out level does, and build mode injects `"low"` for them by default.
- **The set is now `TOP_EFFORT_BY_DEFAULT`, not `MAX_EFFORT_BY_DEFAULT`.** The
  old name asserted a level that only Kimi has: DeepSeek's ladder tops out at
  `xhigh` and has no `max`. Membership is keyed on the behavior — the model
  reasons at the top of *its own* ladder when the field is absent — and the
  gate's refusal message says that rather than naming `max`. Provenance now
  differs per entry, which the code comment records: `kimi-k3` from a reported
  `default_effort` in `GET /v1/models`, the DeepSeek pair from the wire
  measurement above, because DeepSeek's `/models` carries no effort metadata.
  A constant is all that was renamed: the runner still keeps no per-provider
  tier table, so `--effort max` on DeepSeek is passed through and the
  provider's own response is the authority, as before.
- **One default changed for direct callers.** Build mode with `deepseek` and
  no `--effort` used to send the field absent — upper-tier reasoning — and now
  sends `"low"`. Cheap by the same measurement: reasoning volume does not rank
  DeepSeek's tiers (`low` spanned 530–1,239 reasoning tokens against `high`'s
  835–2,792, heavily overlapping), so the tiers behave as on/off rather than as
  a dial. The skill is unaffected — it has always passed `--effort` explicitly
  for DeepSeek. Pass it yourself to keep the old behavior.
- Membership stays **model-keyed, not provider-keyed**: an override to an
  unrecognized id via `SECOND_OPINION_DEEPSEEK_MODEL` is still not injected and
  still not gated — set `--effort` explicitly when overriding, exactly as for
  Kimi. Unchanged, restated because the set grew.
- **Ships the DeepSeek corrections made after 0.2.3.** They landed in `skills/`
  as documentation and so reached no installed profile until now: pricing was
  stale and the two tiers swapped (flash $0.44/M in, $0.22 off-peak; pro
  $1.32/M), `xhigh` works on `deepseek-v4-flash` too and not just `-pro`, and
  `deepseek-chat`/`deepseek-reasoner` are gone from `/models` yet still answer,
  silently resolving to `deepseek-v4-flash` — so the "reasoner" alias quietly
  buys the cheap tier.
- 148 tests pass (four new: the gate on both v4 models with the field unset and
  with `low`, the `"low"` injection in `resolve_effort`, and a build-mode run
  observed on the wire).

## 0.2.3 — 2026-08

- **A review the provider cut off no longer reports as `completed`.** The
  runner sends no `max_tokens`, so a backend's own output cap can end a review
  mid-sentence while the HTTP call succeeds — and until now that landed as a
  short review under a truthful-looking `completed` envelope, with nothing to
  distinguish it from a model that simply had little to say. The runner now
  reads the provider's finish reason (`choices[0].finish_reason`, or
  `candidates[0].finishReason` on gemini), records it in the envelope as
  `finish_reason`, and reports `partial` — exit 3 — when it is a cap
  truncation.
- **Only a cap reason downgrades the status.** `length` and gemini's
  `MAX_TOKENS` mean the review stops mid-sentence; everything else a provider
  might report (`content_filter` and the like) stays `completed` with the
  reason visible in the envelope. `partial` instructs the reader to discard the
  final finding, so a false `partial` destroys real work — the allowlist is the
  safe side.
- **A cap reached before any review text arrives is a new deterministic
  failure, `output_cap`.** Reasoning runs first on the reasoning-by-default
  backends, so a small enough cap is spent entirely on thinking and the content
  comes back empty — which the runner classified as `empty` and retried four
  times, each attempt billed for the identical truncation. It now fails on the
  first attempt and says what to change.
- Verified 2026-08-20. Wire shape: z.AI `glm-5.3` (`"length"`) and
  `gemini-3.1-pro-preview` (`"MAX_TOKENS"`), both delivered in the same SSE
  event as the usage totals. End to end through the runner: `kimi-k3` capped at
  300 tokens returned `partial`, exit 3, `finish_reason: "length"`, 1320
  characters of review on disk cut mid-sentence — the same run reported
  `completed` before this release; `glm-5.3` capped at 1500 and at 4000 tokens
  returned no content at all and now fails once instead of four times. The other
  four backends are unprobed; a reason a provider never sends is reported as
  absent, never as a clean stop.
- **A refused run no longer leaves the previous run's request body behind.**
  Build mode writes `<base>-request.json` only after the gate and key checks
  pass, so at a reused base a refusal used to leave the earlier body looking
  like this run's. It is now cleared as soon as the output base is known,
  alongside the stale envelope. Build mode only — in legacy mode that path can
  be the caller's own input file, which is the documented hand re-run.
- The launch templates' `rm -f` prefix clears `review-request.json` too, which
  covers the case the runner cannot: an invocation that dies before it parses
  its arguments.
- Docs: `<scratchpad>` named among the FAILED recipe's deliberately generic
  placeholders; the root README describes `launch.txt` as the authoritative
  copy of the command rather than claiming byte-equality with a message the
  reader may no longer have.
- 144 tests pass (125 + 19 for the above).

## 0.2.2 — 2026-08

- **z.AI default is now `glm-5.3`.** The access gate that blocked `glm-5.3` on
  standard API keys in 0.2.1 has lifted: on 2026-08-20 a live completion on a
  standard key succeeded (raw call and a full runner streaming pass, envelope
  `completed`, reasoning on by default, ~15 s on a small prompt). That is the
  promotion rule 0.2.1 set — a newer id moves in only after one live completion
  on it succeeds — firing as written; the rule itself is unchanged.
- Documentation plus the one-line default in `DEFAULT_MODELS`; the runner's
  logic is unchanged and its 125 tests still pass.

## 0.2.1 — 2026-08

- **z.AI re-verified 2026-08-16.** `glm-5.3` (launched ~2026-08-13) appears on
  `GET /api/paas/v4/models`, but a completion on a standard API key fails with
  error 1220, "You do not have permission to access glm-5.3" — at launch it is
  gated to the GLM Coding Plan / ZCode, with plain API access staged to follow.
  `glm-5.2` stays the z.AI default (control probe: completes fine, still
  reasons by default).
- **A listing is not access.** That falsifies the "newest on `/models` wins"
  rule the skill gave for the fast-moving glm-5.x line: promote a newer id only
  after one live completion on it succeeds. api-reference.md carries the
  finding; SKILL.md and the skill README keep a pointer to it.
- Documentation only — the runner is unchanged and its 125 tests still pass.

## 0.2.0 — 2026-07

The fork prepares, the main session launches. Every review used to run
*inside* the forked skill invocation, which meant a long review's outcome
depended on a fork obeying prose it could just as easily ignore — 0.1.2
existed to make that non-compliance recoverable, not to stop it happening.
0.2.0 removes the option: the fork's tools no longer include a shell, so it
cannot launch anything. It can only build the request and hand back a
concrete, zero-edit command for the main session to run.

- **Breaking: the skill never runs the review itself.** Every review — short
  or long — is launched by the main session from the fork's PREPARED
  handoff. The old `STATUS: NOT-RUN` / `COMPLETED` / `PARTIAL` fork replies
  are retired; a fork now only ever returns `PREPARED` or `FAILED`.
- **Breaking: fork toolset narrowed.** `disallowed-tools` on the skill
  frontmatter removes Bash, PowerShell, and the dispatch tools (Agent, Skill,
  Workflow, ToolSearch, SendMessage, Monitor, CronCreate, RemoteTrigger) from
  the fork, so it structurally cannot run the runner, spawn a subprocess, or
  hand the job to another agent — E1-verified 2026-07-31.
- **Breaking: no more silent key-fallback.** The 0.1.x fork pre-checked API
  keys and silently fell back to Gemini when the default backend's key was
  missing. The 0.2.0 fork cannot check keys — it has no shell — so a
  missing-key default-routed review now costs one failed launch (a typed
  `usage_error` naming the key and the resolved provider/model, seconds
  after launch) plus a reroute.
- **Added: runner build mode.** `run-request.py --prompt-file <path> [--model
  <id>] [--effort <level>] <provider> <output-base>` has the runner compose
  the API request body itself from a plain prompt file, instead of requiring
  a pre-assembled `request.json` (legacy mode, still supported). That's what
  makes the no-shell fork possible: the fork no longer has to build JSON by
  hand before handing off — it writes the prompt and the launch command, and
  build mode does the composing when the main session runs that command.
- **Added: `SECOND_OPINION_<PROVIDER>_MODEL` resolution in build mode.** The
  env override is read at build time when picking the model; legacy mode
  still never reads it.
- **Added: model-keyed low-effort injection for `kimi-k3`** — the old "always
  set `reasoning_effort` on kimi-k3" prose rule from the fork, now enforced
  in code at build time. **Added: gemini `--effort` validation** — gemini has
  no `reasoning_effort` parameter, so an `--effort` flag against a gemini
  target is a usage error rather than silently ignored.
- **Added: `os.makedirs` on the output base.** Both legacy and build mode
  now create missing output directories instead of failing on them.
- **Added: `<base>-request.json`**, the built request artifact, and
  **`launch.txt`**, the handoff command the fork's PREPARED message tells
  the main session to run.
- **Added: self-clearing launch command.** The command in `launch.txt` opens
  with `rm -f` against the WORKDIR's stale `review-envelope.json` and
  `review-text.md` before it runs, so a second launch against a re-prepared
  WORKDIR can't be misread against leftovers from the first.
- **Changed:** legacy invocations with unknown `--flags` — previously
  swallowed silently and treated as positional arguments — are now a
  `usage_error`. Malformed-invocation error text is reworded to match.
- **Changed:** the gate's refusal message and its "size" reason are reworded.
  The old refusal text named "a skill fork" specifically; that framing
  stopped being true once forks lost the ability to run anything, so the
  wording is now mode-agnostic. The substrings every test pins — the prefix
  `long-path request refused: `, the remedy `trim the prompt`, the remedy
  `set reasoning_effort to "low"` — are unchanged.
- **Unchanged:** legacy CLI acceptance for every documented invocation, the
  envelope contract and file, the gate's size/effort thresholds, exit codes.
- **Removed:** the `jq` dependency and every `jq` invocation pattern from the
  docs. The fork used to build `request.json` by hand with a temp-file +
  `jq --rawfile` recipe; build mode does that composing now, so nothing
  shells out to `jq`.
- 59 new tests (125 total), covering build mode end-to-end and the strict
  CLI grammar (the narrowed fork toolset is verified by the manual E1 probe,
  not the unit suite).

## 0.1.2 — 2026-07

Long-path handoff hardening, and the runner's outcome becomes an artifact. On 0.1.1
a forked review launched its own background run instead of handing it back, ended by
saying it would wait for a completion notification that could not arrive, and left a
finished 10.9 KB review unread for ~45 minutes (2026-07-30, one of two long-path
invocations).

- **New: `<output-base>-envelope.json`.** The runner writes the same envelope it
  prints on stdout to disk as well, atomically, when a run reaches a terminal
  outcome — so the outcome survives a launcher that dies first. That file appearing
  is the completion signal, and it carries `status`, `text_path`, `chars`, `usage`
  or `error_class`. What its *absence* does and does not prove is documented in
  api-reference.md.
- **`emit()` hardened — a bug fix in its own right.** A failed stdout write (a
  `BrokenPipeError` when the reader is gone, i.e. precisely the orphan case) used to
  escape into the catch-all, which emitted a second envelope and then died with an
  uncaught traceback. Both sinks are now best-effort and `emit()` is terminal, so a
  dead reader cannot change a run's recorded outcome.
- A `usage_error` now leaves a file where before it left nothing: a main session
  that forgot `--long`, or ran with no API key, finds a typed explanation on disk
  instead of silence.
- Every final message names the artifacts the run left, where they exist — a failed
  run has only the log, and a run that never started has neither.
- New: ARCHITECTURE.md — components, channels, the files a run leaves, and what
  survives what.
- 12 new tests (66 total), led by regressions for the two runner bugs above.
- The NOT-RUN template no longer hands the fork a copy-pasteable
  `run_in_background: true` — the one call the skill forbids it to make. The
  requirement is now prose addressed to the main session, with the reason: a
  foreground Bash call dies at 10 minutes and orphans the runner.
- The skill's own description names the output glob, so the main session can find
  a long review's result even if the fork's final message tells it nothing.
- The long path no longer passes `ATTEMPTS=1`, so the runner's default of 4
  applies and a transient 429 is retried rather than ending the run. Cost: a
  failing long run can now use its full 90-minute `DEADLINE` instead of ~30
  minutes.
- What 0.1.2 guarantees is that a result is recoverable, not that a fork obeys:
  with one non-compliant run out of two observed, the compliance edits are
  unvalidated by design.

## 0.1.1 — 2026-07

- A forked review that receives no target now returns
  `STATUS: FAILED — no target supplied` instead of asking a clarifying question
  a fork has no user to answer. Empty `$ARGUMENTS` inside a fork is an upstream
  argument-delivery failure, observed once and not reproducible since; nothing
  is sent to any backend when it happens.
- README troubleshooting: how to recognize that failure, and how to drive
  `run-request.py` from the main session as a fallback (runner path given for
  both marketplace and clone installs).
- Documentation only — the runner is unchanged.

## 0.1.0 — 2026-07

Initial release.

- Skill with seven backends: Kimi (`kimi-k3`, default), Gemini, OpenAI,
  DeepSeek, xAI, z.AI (GLM), MiniMax.
- MiniMax M-series `<think>` chain-of-thought blocks stripped from review
  text (verified live on `MiniMax-M3`, 2026-07-23).
- Streaming runner (`scripts/run-request.py`, stdlib-only) with classified
  retries, a size/effort gate against orphaned long runs, partial-output
  recovery, and a single-JSON-envelope contract.
- Per-provider default-model overrides via `SECOND_OPINION_<PROVIDER>_MODEL`.
- Model tables and provider behavior verified 2026-07.
