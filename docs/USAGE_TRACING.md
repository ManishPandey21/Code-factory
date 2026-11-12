# Local usage tracing

Every parsed `factory.py` invocation with a resolvable Git repository appends a
start event and a finish event to the Git common directory's
`infra-factory/usage.sqlite3`. This includes previews (marked `preview: true`),
failed commands, status and hold/release calls. `--help`, argument-parser errors,
and invalid repository paths do not start an operation and have no local trace
destination. `init` preview may create only this metadata store; it still does
not write project configuration, tickets or candidate worktrees.

Each event has a schema version, random invocation ID, command name, process ID,
UTC timestamp and preview flag. Finish events add exit code, outcome and elapsed
milliseconds. The trace records command executions, not model invocations or
claims that every ticket succeeded. For example, a run that selects no tickets
because they are held can successfully finish without allocating work.

No prompts, issue bodies, ticket contents, paths, raw arguments, reasons,
credentials, environment variables, provider output or test logs are collected.
There is no network request, telemetry service, upload, tracking dependency,
background worker or automatic export. SQLite is already part of the Python
standard library; each event is a short transaction and the connection closes
before command execution. Concurrent local processes serialize through SQLite.
New trace databases are created with mode 0600 on POSIX.

## Inspect events

Use your Git common directory, not an application-source path:

```sh
python -c "import sqlite3; c=sqlite3.connect('/absolute/git-common-dir/infra-factory/usage.sqlite3'); print('\n'.join(r[0] for r in c.execute('SELECT event FROM usage_events ORDER BY sequence'))); c.close()"
```

Match `start` and `finish` using `invocation`. SIGINT/SIGTERM produce an
`interrupted` finish with exit code 130 when the controller can unwind normally.
An unmatched start records a process that did not finish tracing, including a
hard kill or host crash. It does not establish whether external work completed.

The trace has no automatic retention policy. After stopping active factory
processes, operators may archive or remove `usage.sqlite3` without changing the
ledger, holds, evidence or attempt history. The next invocation creates it again.

## Trust boundary

This store is observational metadata, separate from `ledger.sqlite3` and all
verification manifests. Nothing reads tracing data to authorize actions, clear a
hold, reset attempts, approve code or establish READY. It is not signed,
independently authenticated, billing evidence or proof of model/test quality;
the same local user can alter it, as with other local files.

Tracing is best effort under storage failure. A missing/unwritable/corrupt store
or database timeout emits a generic warning on stderr and preserves the command's
normal behavior and exit status. It never redirects stdout, bypasses gates or
turns a failed action into success. Start/end records are committed immediately,
but failures or abrupt termination can leave incomplete observations. Trace
health must therefore be checked before claiming an exhaustive usage history.
