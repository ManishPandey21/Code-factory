# Specialist review, risk, repair and live status

## Configure Claude or Codex

Existing configurations keep their standards/spec reviews. To opt in, copy and
adapt [review-policy.json](../examples/review-policy.json) to your project. Then
run the usual `configure.py` with `--review-policy /path/to/review-policy.json`:

```bash
python /path/to/Code-factory/configure.py --repo /path/to/project \
  --tdd-skill /installed/test-driven-development/SKILL.md \
  --provider codex --model YOUR_MODEL_ID \
  --review-policy /path/to/review-policy.json
```

Use `--provider claude --model YOUR_FULL_CLAUDE_MODEL_ID` for Claude. The existing
`--skills-inventory` option can replace `--tdd-skill`. Preview first, then use
`--apply` and review/commit the project configuration. Existing backup handling
still applies. Overrides such as `--route reviewer_security=claude:MODEL:high`
and `--route risk_assessor=codex:MODEL:high` choose a provider per role. No model
IDs or authenticated providers are assumed by the example.

Specialist names map to `commands.reviewer_NAME`. At most eight are supported.
Missing command mappings fail before dispatch; a specialist never silently uses
the generic reviewer. Each selected reviewer gets a separate cold Git copy and
fresh bridge profile. Standards and spec remain mandatory. Matching uses actual
changed paths, including deleted paths, with case-sensitive Python `fnmatch`
globs: `*` can cross `/`, and `**/auth/**` does not match root `auth/`, so list both
when needed. The example is a starting point, not a universal security policy.

## Independent risk and human review

When `review_policy.risk` is configured, a separate `risk_assessor` reads the
candidate and ticket without builder transcripts or review conclusions. Its
structured assessment names the exact head/base and every changed file. The
controller raises its result to meet configured minimum/path floors; critical
tickets always have critical risk. An assessor may request a human even at low
risk. `human_review_levels` must include every level above its lowest threshold.

A passing candidate requiring a human enters `AWAITING_HUMAN`, reserves its paths,
and cannot publish. `run --execute` exits successfully when work has reached READY
or AWAITING_HUMAN; this does not imply human approval. Inspect `status`, the diff,
checks, all lenses and risk rationale, then an authorized human can attest:

```bash
python factory.py approve --repo /path/to/project --ticket TICKET-001 \
  --head EXACT_CANDIDATE_SHA --risk-digest EXACT_RISK_DIGEST \
  --reviewer 'Human name' --note 'What was reviewed and why the risk is accepted'
```

Take the digest from `review_json.risk.digest` in `status`. Approval rechecks the
candidate, base, config, EGM handoff and artifacts. It is bound to that head,
configuration and risk digest. It cannot authorize a repaired candidate. This
local CLI records an operator attestation; it does not authenticate the person
named, enforce OS roles or replace GitHub branch protection. Agents must not
invent a human attestation or approve their own work. Holds block approval.
`verification_current` on AWAITING_HUMAN describes current technical evidence;
the state still means human review is outstanding.

## Bounded repair

Opt in before the initial run by adding this to the project configuration:

```json
"repair_policy": {
  "max_repairs": 2,
  "github": {"repository": "owner/repo", "workflow_ids": [12345678]}
}
```

The GitHub section is optional for local review repair. Use real workflow IDs
from the target repository. Never enable a broad workflow allowlist just to make
a failure eligible. Config changes invalidate existing verification, so configure
this before creating the candidate you intend to repair.

```bash
python factory.py repair --repo /path/to/project --ticket TICKET-001 \
  --head EXACT_CANDIDATE_SHA --source review
python factory.py repair --repo /path/to/project --ticket TICKET-001 \
  --head EXACT_CANDIDATE_SHA --source review --execute
# Or use a completed failed allowlisted GitHub Actions run:
python factory.py repair --repo /path/to/project --ticket TICKET-001 \
  --head EXACT_CANDIDATE_SHA --source github --run-id 123456789 --execute
```

Each explicit invocation performs **one** fresh repair attempt, then stops for
inspection. Preview validates the source without consuming an attempt. A local
source must be a recorded CHANGES_REQUIRED review with nonempty findings and
unchanged raw review/test artifacts. Inconclusive verdicts, missing local tests
and pasted issue comments cannot supply repair authority.

For GitHub, the controller fetches authenticated API metadata using `gh api`,
checks the repository and head repository, exact candidate SHA, allowlisted
workflow ID, completed failure/timed-out conclusion, and push/pull_request event.
Fork runs and pull_request_target are rejected. Attempt-specific jobs must match
the same head/run/attempt. The run is fetched again to detect reruns during
collection. Evidence includes failed job/step names; full logs and annotations
are not downloaded. If these diagnostics are insufficient, the attempt may block
and needs operator investigation. The project owner is responsible for keeping
allowlisted workflows and their dependencies trusted.

The controller retains hashed source receipts and records a repair event before
execution. A given ticket/head can be consumed only once. It starts a fresh
worktree from the original base, provides the previous candidate and findings as
data, and reruns all checks, selected reviews and risk assessment. Failed or
interrupted attempts count; replacement tickets inherit history. `max_repairs`
limits total attempts to `1 + max_repairs`, also capped at three, so ordinary
retries consume the same budget. It stops on failure, success or human review;
there is no unattended loop or automatic publication. Holds and overlapping
reserved paths prevent repair. The retained prior worktree must still be clean.

A repaired candidate gets a new branch. An existing draft remains historical;
this version does not update/force-push it. Explicitly publish the newly reviewed
candidate and close the old draft through your normal process. No merge or
deployment is automatic.

## Live ledger view

```bash
python factory.py events --repo /path/to/project --after 0 --limit 100
python factory.py events --repo /path/to/project --after 0 --follow
python factory.py dashboard --repo /path/to/project --port 8765
```

Open `http://127.0.0.1:8765`. The dashboard shows tickets, candidate SHAs, attempts,
recorded risk/approval, holds and an event stream. Search by ticket, state or title.
It polls every two seconds and retains the latest 1,000 events in the browser.
The API returns consistent read-only SQLite snapshots with monotonically ordered
cursors and up to 500 events per page. Follow the returned cursor/has_more fields
to avoid skipping events. Ticket inventory is returned in full; very large ledgers
may need future server-side ticket pagination.

No config or valid provider login is needed to read the ledger. Missing ledgers
are never created by reads. The server binds only to loopback, requires local
Host/same-origin requests, serves local assets with a restrictive content policy,
and exposes no mutation endpoints. Ticket text renders as text, not HTML. Run it
under the local operator account; it is not a remotely authenticated dashboard.
States are recorded history, not a live certificate of filesystem/remote CI
validity. `status` and `publish` perform the current evidence checks. Ctrl-C stops
the viewer.
