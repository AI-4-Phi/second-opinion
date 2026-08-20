# Architecture

How the pieces of this plugin fit together, as they are. Descriptive only — no
proposals. Verified against the shipped code 2026-07-31 (plugin 0.2.0).

For what the skill *should* do, read
[SKILL.md](skills/second-opinion/SKILL.md) — that file is the contract, and this
one must not restate it. For provider endpoints, model tables, measured timing,
and the envelope/gate/orphan-cleanup facts, read
[api-reference.md](skills/second-opinion/api-reference.md).

## Components

| Piece | What it is | Model / runtime |
|---|---|---|
| Main session | The conversation the user is in. Invokes the skill, then launches the runner as a background Bash task once the fork hands back a PREPARED command; never reads `SKILL.md` itself. | The session's own model |
| Forked skill | A subagent started by the invocation. Reads `SKILL.md` and does the plumbing: locate the target, inline it, compose the review prompt, choose backend and effort, Write `prompt.txt` + `launch.txt`, hand back PREPARED (or FAILED). Tools: `Read`, `Glob`, `Grep`, `Write` — no shell, no dispatch (`disallowed-tools` blocks `Bash` and every delegation tool). | `sonnet`, pinned in frontmatter |
| Runner | `scripts/run-request.py`. Stdlib Python, no venv. Dual-mode CLI: build mode composes the request itself from `--prompt-file`/`--model`/`--effort`, legacy mode takes a pre-built `request.json`; either way it calls one provider endpoint, streams the response to disk, and prints one JSON envelope. | `python3` subprocess |
| Provider | Kimi, Gemini, OpenAI, DeepSeek, xAI, z.AI or MiniMax, over HTTPS. Reads no local files. | External API |

## Channel topology

```
        ┌──────────────────┐
        │   main session   │  invokes the skill; sees only the fork's final message
        └────────┬─────────┘
                 │  ▲  final message ── the only thing the fork PUSHES anywhere
                 ▼  │  (PREPARED, or FAILED)
        ┌──────────────────┐
        │   forked skill   │  Read, Glob, Grep, Write — no shell, no dispatch
        └────────┬─────────┘
           Write │
                 ▼
   <WORKDIR>/prompt.txt + launch.txt   (fork-written; exist BEFORE the
                                        runner starts)

        main session launches launch.txt's command as a BACKGROUND Bash task
                 │
                 ▼
        ┌──────────────────┐
        │  run-request.py  │ ──────► provider API (SSE stream by default)
        │  build mode      │
        └────────┬─────────┘
                 │ writes while running          │ writes when the run ends
                 ▼                               ▼
  review-request.json  review-text.md  review-log.txt  review-envelope.json
  (built body,          (grows as the   (prose trace,   (the same envelope stdout
   after gate + key      stream         append-mode)     carried — the typed outcome,
   checks pass)          arrives)                        as an artifact)
                                        review-pid.txt   review-raw.json
                                        (exists while    (raw HTTP response
                                         the run does)    body)
```

Two asymmetries in that picture explain most of the skill's rules:

- The fork's final message is its only **push** channel. Files it leaves behind are
  a **pull** channel: they persist, but only a reader who knows to look finds them.
- Stdout reaches exactly one consumer — whoever launched the process. A launcher
  that dies first would take the outcome with it, which is why the envelope is also
  an artifact.

## Where the files live

The fork's work dir is `<session scratchpad>/second-opinion-<slug>`, and that
scratchpad is the **main session's** — a fork does not get its own (verified
2026-07-30: an incident's work dirs and a fork dispatched from a different session
each landed under their respective main session's scratchpad UUID). So a glob under
the main session's scratchpad reaches any fork's output.

The runner is given an output base (`<WORKDIR>/review`) and derives every file from
it: `-raw.json`, `-text.md`, `-log.txt`, `-pid.txt`, `-envelope.json`, and (build
mode only) `-request.json`.

## The launch boundary

Three runtime facts force it:

1. A Bash tool call dies at 10 minutes, so a long request cannot run synchronously
   inside the fork.
2. A background task started in a fork keeps running and billing, but its
   completion notification dies with the fork.
3. A foreground child outlives the fork that started it, so a killed fork leaves the
   runner running — hence `DEADLINE` and the pid file.

So the fork never runs the runner itself: every review is prepared — Written to
`prompt.txt` and `launch.txt` — and handed to the main session, which launches the
exact `launch.txt` command as a background Bash task with `--long DEADLINE=5400`.
The runner's gate enforces the same boundary independently and refuses a request
that does not pass `--long`, because a prose rule gets skipped; in practice that
gate only ever faces a **direct caller** who drives the runner by hand, bypassing
the fork — see "Envelope, gate, and orphan cleanup" in
[api-reference.md](skills/second-opinion/api-reference.md).

## The outcome path

`emit()` is the single choke point: `completed`, `partial`, `failed`, `usage_error`
and `cli()`'s catch-all `internal` all pass through it, and each one persists the
envelope, prints it, and exits. No path writes an outcome and continues, and neither
sink can change the outcome: a dead stdout reader and an unwritable directory are
both swallowed, because an escaping error would re-enter the catch-all and emit a
second, contradictory envelope. The status → exit code table lives in
[api-reference.md](skills/second-opinion/api-reference.md).

Lifetime of a run's files:

```
    prompt.txt, launch.txt written by the fork         (before the runner starts)
t0  output base known → any previous envelope removed, and (build mode only)
    any previous -request.json with it, so a refused run leaves neither
    (build mode only) gate + key checks pass → -request.json written
t1  pid file written                              [pid]
t2  attempts, streaming                           [pid] [text ▓▓▓░░ growing]
t3  emit(): envelope written FIRST                [pid] [text ▓▓▓▓▓] [ENVELOPE]
t4  stdout (best-effort), SystemExit
t5  atexit removes pid                                  [text ▓▓▓▓▓] [ENVELOPE]
```

The envelope appears only at `t3`, so its presence never means "in progress"; it is
written before stdout so that a reader who finds the process gone still finds the
outcome.

Consequences worth knowing before changing anything here:

- **`-text.md` is readable while incomplete.** The runner flushes each chunk as it
  arrives, deliberately, so an interrupted run leaves a usable partial review. Its
  existence therefore says nothing about whether the run finished.
- **The pid file is evidence, not proof.** Its write is best-effort (a missing pid
  file must never block a request), `atexit` and the SIGTERM/SIGINT handler remove
  it, and `SIGKILL` runs neither — so it can be absent during a live run or present
  after a dead one.
- **`-log.txt` is prose, and append-mode across runs.** It can be matched but not
  parsed, and its success line differs by mode: `COMPLETED`/`PARTIAL attempt N` when
  streaming, `SUCCESS attempt N` under `--no-stream`.
- **A cancelled or killed run leaves no typed record at all** — no envelope either.
  SIGTERM, SIGINT and SIGKILL all end the process without reaching `emit()`.
- **The envelope describes the latest invocation at that output base.** A new run
  removes the previous envelope as soon as it knows its base, but an earlier run's
  `-text.md` can outlive it, which is why a reader checks `status` first. One output
  base per invocation is the way to keep the association unambiguous.

## Why the review is never carried in a message

The fork names `-text.md`'s path in its PREPARED message before anything runs; the
runner later writes the review there. Neither channel carries the content. Two
reasons, both structural: a fork's message is the narrowest channel in the system,
and a summary of a technical review drops the specific cited objection that makes
an outside opinion worth having.

## Dependencies

`python3` (stdlib only) for the runner. Provider API keys come from the environment
of the Claude Code process — the runner reads exactly one per provider and never
writes them anywhere.
