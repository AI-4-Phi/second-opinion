# Architecture

How the pieces of this plugin fit together, as they are. Descriptive only — no
proposals. Verified against the shipped code 2026-07-30 (plugin 0.1.1).

For what the skill *should* do, read
[SKILL.md](skills/second-opinion/SKILL.md) — that file is the contract, and this
one must not restate it. For provider endpoints, model tables and measured timing,
read [api-reference.md](skills/second-opinion/api-reference.md).

## Components

| Piece | What it is | Model / runtime |
|---|---|---|
| Main session | The conversation the user is in. Invokes the skill; never reads `SKILL.md` itself. | The session's own model |
| Forked skill | A subagent started by the invocation. Reads `SKILL.md` and does the plumbing: locate the target, inline it, build `request.json`, route, report. Tools: `Bash`, `Read`, `Glob`, `Grep`. | `sonnet`, pinned in frontmatter |
| Runner | `scripts/run-request.py`. Stdlib Python, no venv. Calls one provider endpoint, streams the response to disk, prints one JSON envelope. | `python3` subprocess |
| Provider | Kimi, Gemini, OpenAI, DeepSeek, xAI, z.AI or MiniMax, over HTTPS. Reads no local files. | External API |

## Channel topology

```
        ┌──────────────────┐
        │   main session   │  invokes the skill; sees only the fork's final message
        └────────┬─────────┘
                 │  ▲  final message  ── the only thing the fork PUSHES anywhere
                 ▼  │
        ┌──────────────────┐  short path: runs the request itself
        │   forked skill   │  long path : prepares it and hands it back
        └────────┬─────────┘
           Bash  │  ▲  stdout: exactly ONE JSON envelope
                 ▼  │
        ┌──────────────────┐
        │  run-request.py  │ ──────► provider API (SSE stream by default)
        └────────┬─────────┘
                 │ writes while running          │ writes when the run ends
                 ▼                               ▼
   request.json  review-text.md  review-log.txt  review-envelope.json
   (input)       (grows as the   (prose trace,   (the same envelope stdout
                  stream         append-mode)     carried — the typed outcome,
                  arrives)                        as an artifact)
                                 review-pid.txt
                                 (exists while the run does)
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
it: `-raw.json`, `-text.md`, `-log.txt`, `-pid.txt`, `-envelope.json`.

## The short/long boundary

Three runtime facts force it:

1. A Bash tool call dies at 10 minutes, so a long request cannot run synchronously
   inside the fork.
2. A background task started in a fork keeps running and billing, but its
   completion notification dies with the fork.
3. A foreground child outlives the fork that started it, so a killed fork leaves the
   runner running — hence `DEADLINE` and the pid file.

So requests split by cost: small and low-effort ones run synchronously inside the
fork; large (≥ 32 KB `request.json`) or high-effort ones are prepared by the fork
and launched by the main session as a background task. The runner enforces the same
split itself and refuses a long request that does not pass `--long`, because a prose
gate gets skipped — see the gate in
[SKILL.md](skills/second-opinion/SKILL.md).

## The outcome path

`emit()` is the single choke point: `completed`, `partial`, `failed`, `usage_error`
and `cli()`'s catch-all `internal` all pass through it, and each one persists the
envelope, prints it, and exits. No path writes an outcome and continues, and neither
sink can change the outcome: a dead stdout reader and an unwritable directory are
both swallowed, because an escaping error would re-enter the catch-all and emit a
second, contradictory envelope. The status → exit code table lives in
[SKILL.md](skills/second-opinion/SKILL.md).

Lifetime of a run's files:

```
t0  output base known → any previous envelope removed
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

The runner writes the review to `-text.md` and reports its path; the fork relays the
path, not the content. Two reasons, both structural: a fork's message is the
narrowest channel in the system, and a summary of a technical review drops the
specific cited objection that makes an outside opinion worth having.

## Dependencies

`python3` (stdlib only) for the runner, and `jq` for the request-building pattern
the fork uses. Provider API keys come from the environment of the Claude Code
process — the runner reads exactly one per provider and never writes them anywhere.
