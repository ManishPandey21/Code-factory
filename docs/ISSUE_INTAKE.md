# GitHub Issue intake and linking

Issue intake reads GitHub through your authenticated `gh` CLI and writes only the
local factory ledger. It never comments, labels, closes, reopens or edits an Issue.
The issue must be open, must be an Issue rather than a pull request, and must belong
to the current checkout's GitHub `origin`. HTTPS and Git-over-SSH origin URLs are
supported. GitHub Enterprise hosts are not currently supported.

Issue text is untrusted source material. Review it and prepare a normal factory
JSON ticket with explicit paths, dependencies, acceptance criteria and all spec
sections. EGM projects still need their approved handoff. The factory does not
infer authorization or executable scope from a title, body, labels or comments.

## Import an approved ticket with its source

```sh
python factory.py intake --repo /project --ticket /tickets/ISSUE-12.json \
  --issue https://github.com/owner/project/issues/12
python factory.py intake --repo /project --ticket /tickets/ISSUE-12.json \
  --issue https://github.com/owner/project/issues/12 --execute
```

The first command fetches the source and previews the complete validation path,
rolling back all local inserts/events. `--execute` atomically creates the ticket,
source snapshot and audit events. The snapshot includes the stable GitHub ID,
canonical URL, repository, number, title, body, update timestamp and digest. It is
visible as `source_issue` in `status` and survives process restarts.

A repeated request with the same validated ticket and source snapshot is
idempotent: no extra ticket/event, reset attempt budget, retry or hold release.
Changed ticket content or source snapshots fail closed rather than silently
replacing the approved request. One issue is linked to one ticket, and one ticket
to one source issue; a second ticket ID cannot duplicate the same issue. For a
larger issue, make the linked ticket the dependency/coordination ticket and create
explicit reviewed child tickets. Do not use new IDs to evade held work.

## Link an existing ticket

```sh
python factory.py link-issue --repo /project --ticket TICKET-001 \
  --issue https://github.com/owner/project/issues/12
python factory.py link-issue --repo /project --ticket TICKET-001 \
  --issue https://github.com/owner/project/issues/12 --execute
```

New links require an inactive, unheld and unpublished ticket. Exact replays make
no changes and are allowed while held. Link changes cannot release a hold or
alter verified ticket content. Linking is recorded separately from acceptance
and execution state. Existing links and source snapshots are immutable through
these commands; changed requirements need explicit reconciliation by the
coordinator, not a silent refresh.

Publication previews include the source URL. A newly created draft PR includes a
`Refs https://github.com/.../issues/...` line using the recorded link. This is a
reference, not an automatic closing instruction. Linked publication pins `gh` to
the origin repository and checks returned PR URLs; ambient `GH_REPO` settings
cannot redirect the link to another repository. Intake does not publish anything;
existing publication authorization, evidence, holds and human-review gates apply.
Already-published drafts cannot be linked retroactively through this command.

Read failures, redirected/mismatched issues, closed issues, PR URLs, malformed
responses and duplicate/conflicting links leave local work unchanged. Source
snapshots live in the private ledger and may contain private issue text; handle
them with the same care as existing ticket descriptions and retained prompts.
