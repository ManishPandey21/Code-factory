# Durable holds and safe repeat submissions

These local controls keep an operator's stop decision separate from test/review
results and prevent a repeated submission from resetting work. They use the
existing private SQLite ledger and coordinator lock. They do not require another
service or change the EGM approval and cold-review gates.

## Inspect a ticket

```sh
python /tools/infra-code-factory/factory.py status --repo /project
```

Each ticket includes `hold_reason` (null when clear), `hold_version` (initially 0),
and `publication_held`. `verification_current` still describes the code/test
snapshot: a READY ticket can be verified and held at the same time. If configuration
or an installed skill is broken, status returns the ledger and a top-level
`configuration_error`; it reports no current verification. Fix that error before
running or publishing. Holds can still be inspected and managed.

## Hold and release inactive work

Read status immediately before each command and use the version actually shown.
The versions and reasons below illustrate a first hold and release:

```sh
python /tools/infra-code-factory/factory.py hold --repo /project \
  --ticket TICKET-001 --hold-version 0 --reason 'Review destination before delivery'
python /tools/infra-code-factory/factory.py release --repo /project \
  --ticket TICKET-001 --hold-version 1 --reason 'Destination reviewed; resume authorized'
```

Both commands require a reason and the current version. Every successful hold,
changed hold reason or release increments the version and writes a local audit
event in the same database transaction. A stale release cannot clear a newer
hold. Changing prompts/configuration, re-running init or restarting the CLI never
releases a hold. Nothing is sent to GitHub by these commands.

Only inactive PENDING, BLOCKED or READY tickets accept hold/release commands.
RUNNING/REVIEWING work must first stop; use the existing interruption and recovery
procedures. A held ticket cannot dispatch, retry, publish, be rejected or be
superseded. It reserves its paths while inactive and unmerged, so another pending
ticket cannot simply take over those paths. Unrelated tickets can still run.
Release a hold explicitly before rejecting or replacing its ticket.

Holds do not undo external operations or stop a process already holding the
coordinator lock. They do not prevent a human from independently merging code on
GitHub. If exact-ancestry reconciliation discovers that a held candidate was
merged externally, its held paths no longer block new work; its hold record stays
as history. No automatic merge, cancellation, credential revocation or rollback
is implied. The controls assume the trusted local controller model, not protection
against another process editing the database. Older factory binaries do not know
about holds: do not downgrade or run them against this ledger while relying on
these controls.

The controls table is created on the first successful hold, under the coordinator
lock. Existing ledgers without that table read as version 0/unheld. No tickets,
checks, attempts or events are removed. Back up the full private runtime,
including a consistent SQLite snapshot and retained worktrees/logs.

## Repeat a submission after a lost response

```sh
python /tools/infra-code-factory/factory.py add --repo /project \
  --ticket /tickets/TICKET-001.json --idempotent
```

A new ID creates one PENDING ticket and returns `replayed: false`. Repeating the
same ID with identical validated contents returns `replayed: true`, the existing
state and attempts used. Key ordering and JSON formatting do not matter; ticket
path normalization is the same as ordinary intake. Ticket and EGM validation
still apply. Changed scope or metadata is a conflict, never an overwrite.

Replay adds no duplicate event, performs no supersession again, resets no attempts,
starts no process and clears no hold. It is not `retry`. The existing `add` command
without `--idempotent` continues rejecting duplicate IDs. Changed work requires a
new reviewed ticket, including `supersedes` where appropriate to retain attempt
history; release any active hold before replacement.
