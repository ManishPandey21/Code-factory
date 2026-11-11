# v0.4.0 validation — 11 November 2026

Environment: Linux, Python 3.12.14, Git 2.52.0. Standard library only.

| Check | Result |
|---|---|
| Input archive checksums | All entries passed before edits |
| Original v0.3.4 baseline | 131 tests passed, 201.102 seconds |
| New provider/routing tests | 4 tests passed |
| Existing routing regressions | 25 tests passed |
| New EGM handoff tests | 7 tests passed |
| Complete modified suite | **142 tests passed**, 233.903 seconds; no skips or failures |
| Python compilation | All top-level Python modules compiled |
| Host entry-point references | Both resolve to the shared workflow skill |

Command: `python -m unittest discover -s tests -v`.
The complete run includes the targeted suites; counts are not additive.

The EGM integration test uses real Git and actual CLI commands to create a bound
ticket, reject an unbound ticket, execute it to READY with deterministic workers,
and reject stale design state during status/publication checks. Additional tests
reject changed ticket scope, modified committed/uncommitted documents, missing
stages/approval, traversal, symlinks, empty/untracked artifacts and output reuse.
Reviewer prompt checks require both code-review lenses to read the approved design and disregard prior EGM reviewer conclusions. Malformed-ticket CLI input is also checked.
Provider configuration tests cover Claude-only, Codex-only, mixed routing,
preview preservation, backups, missing explicit models and mismatched receipts.

Limits: no live model call, real EGM review, authenticated plugin installation,
GitHub draft publication, Windows/macOS run, merge or deployment. Codex CLI help
was inspected locally; Claude is not installed in this environment. The official
EGM source was read at the commit recorded in EGM_WORKFLOW.md. CLI/auth/provider
and native plugin compatibility still require a live pilot on the user's host.
