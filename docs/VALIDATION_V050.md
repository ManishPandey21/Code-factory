# v0.5.0 validation

Environment: Linux, Python 3.12.14, Git 2.52.0. Core runtime and unittest suite
use the Python standard library. Browser checks use separately installed
Playwright with `/usr/bin/chromium`.

## Automated evidence

Final full suite: **181 tests passed** in 360.161 seconds, no failures or skips.
The complete output is [VALIDATION_V050.log](VALIDATION_V050.log).
The initial 178-test suite passed in 349.837 seconds. Three regressions were
subsequently added for the review findings described below.

New coverage exercises actual Git candidate creation and cold checkouts,
matching/nonmatching specialists, missing command rejection, independent risk
identity and policy floors, human gate/hold behavior, stale approvals, tampered
artifacts, review and CI repairs, consumed candidate identities, bounded attempts,
read-only snapshots, gap-free event cursors, loopback origin checks and rejected
mutation requests. Provider mapping tests cover both Claude and Codex with strict
routing and fresh reviewer profiles for specialist and risk roles.

The optional browser check passed:

```text
python tests/browser_smoke.py --browser /usr/bin/chromium --artifacts /tmp/factory-v050-browser
PASS: live ledger/risk/events, filtering, safe text, desktop/mobile, new hold polling and reconnect without duplicate events
```

The browser fixture uses a hostile HTML-like ticket title and verifies that it
renders as text. It verifies a hold and new event appear through polling, simulates
a connection loss, and verifies reconnection without duplicate events. Desktop
and mobile screenshots were inspected. No application dependencies were added.
Python compilation, JavaScript syntax, Git whitespace checks, and all nine skill
TOC labels/anchors also passed. New tests import successfully from outside the
repository; five focused tests passed from `/tmp`.

## Independent review

The Matt code-review workflow reviewed implementation candidate `e0e679f` against
base `f348de0` using separate standards and specification reviewers.

Standards findings: repair reservation initially committed before the attempt
transition, and repair treated historical merged holds as active reservations.
The fix commits repair claims/events/RUNNING allocation atomically and shares the
state-qualified path-reservation predicate. A fault-injection regression proves
rollback leaves the request replayable and attempts unchanged.

Specification findings: ordinary retries and inherited replacement attempts could
exceed a stricter `max_repairs: 1` limit; historical merged holds could block later
repairs. The fix shares the effective attempt limit across every dispatch path
and reuses the reservation predicate. Real-Git regressions cover both scenarios.

Both independent reviewers rechecked `ed822c2` and confirmed their findings
resolved. The standards reviewer also independently exercised transaction rollback
and replay. Neither reviewer ran the full suite; the coordinator ran it.

## Limits

Workers and GitHub API responses are deterministic fixtures in automated tests.
No paid Claude/Codex execution or live GitHub Actions repair was performed. These
results establish orchestration behavior, not model judgment quality, production
readiness, authenticated human identity or OS isolation. Workflow IDs and provider
credentials must be configured for each target project. Existing drafts are not
force-updated by repair. No automatic merge or deployment is introduced.
