# Google EGM → Infra Code Factory

This integration uses Google's **Elephant–Goldfish Model** for design and the
factory for implementation, cold testing, and code review. The upstream plugin
remains the source of design reviewer personas and standards. It is not bundled
or silently installed. This is an integration, not a fork or a claim of Google
certification.

Source reviewed: [google/elephant-goldfish-model](https://github.com/google/elephant-goldfish-model/tree/0f06dd7230261c00f0e03bd8d3ca8b5a1b898e2b),
commit `0f06dd7230261c00f0e03bd8d3ca8b5a1b898e2b`, 11 November 2026.
See its [workflow](https://github.com/google/elephant-goldfish-model/blob/0f06dd7230261c00f0e03bd8d3ca8b5a1b898e2b/docs/getting_started.md)
and [five-stage protocol](https://github.com/google/elephant-goldfish-model/blob/0f06dd7230261c00f0e03bd8d3ca8b5a1b898e2b/skills/egm-review/SKILL.md).
The upstream notes that this is not an officially supported Google product.

## Install for your host

Install the complete official plugin using one host below, then start a new
session. Inspect the version installed: marketplace commands track the upstream
release, not necessarily the reference commit audited here.

Claude Code:

```sh
claude plugin marketplace add google/elephant-goldfish-model
claude plugin install egm@egm
```

Codex CLI:

```sh
codex plugin marketplace add google/elephant-goldfish-model
codex plugin add egm@egm
```

For desktop installations use the official repository's installation guide.
These commands are documented upstream; no authenticated install or live Claude
session was run during this audit. If your CLI lacks plugin support, update using
its supported installer. Do not copy only upstream SKILL.md files: their linked
personas and standards are required.

This toolkit includes matching `.claude/skills/infra-factory` and
`.agents/skills/infra-factory` entries for sessions opened in its directory.
For a different application, ask either host to read the absolute path to
`skills/infra-factory/SKILL.md` in this toolkit. Keep the toolkit outside that
application; do not replace its existing AGENTS.md or CLAUDE.md.

## Design workflow

| Stage | Elephant/coordinator action | Goldfish input |
|---|---|---|
| Brainstorm | Clarify consequential requirements; save concepts brief | Fresh reviewers challenge the proposal |
| Draft | Write feature specification and detailed implementation plan | No implementation yet |
| Initial zoom out | Check scope and abstraction | Design and approved reading list |
| Comprehension | Inspect the reviewer's paraphrase | Document alone, no previous discussion |
| Design critique | Resolve design, structure and style findings | Design and approved reading list |
| Intermediate zoom out | Recheck coherence after revisions | Current design and approved reading list |
| Implementation readiness | Check whether the plan is actionable | Implementation plan and approved reading list |
| Approval | Human accepts design and disposition of findings | Final artifacts |
| Implementation | Bind tickets, execute factory, inspect code-review evidence | Each builder gets ticket plus approved design |
| Drift | Use `egm-drift-report` after integration | Design and current source |

Claude uses `/egm:egm-brainstorm`, `/egm:egm-draft`, `/egm:egm-review`, and
`/egm:egm-resolve`. In Codex choose the corresponding EGM skill from its skill
picker. An uninterrupted review can consolidate the five reports; it still
requires fresh Goldfish contexts and actual owner approval before implementation.
Do not run the old grill-me/to-spec sequence alongside EGM for the same design.
Ticket decomposition and the configured TDD skill remain part of implementation.

## Configure either provider

Use an actual model ID available to your account. No models are guessed. Both
providers can fill every worker/reviewer role; use repeated `--route` options to
specialize roles. The coordinator's host does not force the worker provider.

```sh
python /tools/infra-code-factory/factory.py init --repo /project --apply
python /tools/infra-code-factory/configure.py --repo /project \
  --tdd-skill /skills/test-driven-development/SKILL.md \
  --provider codex --model YOUR_CODEX_MODEL --effort medium --egm
# After inspecting the printed config, repeat with --apply.
```

For Claude substitute `--provider claude --model YOUR_FULL_CLAUDE_MODEL_ID`.
For mixed routing add, for example,
`--route reviewer_spec=claude:YOUR_FULL_CLAUDE_MODEL_ID:high`.
The bridge validates Claude full-ID syntax at execution. Configuration preserves
checks and verification policy; configure those with real project commands using
[HARDENING_SETUP.md](HARDENING_SETUP.md). Review the one-time backup before
removing it. Commit setup before execution. `--egm` sets `workflow` to `egm`;
classic existing configs remain supported, but a ticket carrying an EGM receipt
is always validated even in classic mode.

## Bind an approved design to a ticket

Commit the design and review reports to the application's base branch first.
They must be nonempty, unchanged, regular files within the repository. Use the
actual human's approval attribution and a reference/note explaining disposition
of findings. The following paths and names are examples, not approval evidence:

```sh
python /tools/infra-code-factory/egm.py --repo /project \
  --ticket /tickets/TICKET-001.json --design docs/designs/feature.md \
  --report initial_zoom_out=docs/designs/reviews/initial.md \
  --report comprehension=docs/designs/reviews/comprehension.md \
  --report design_critique=docs/designs/reviews/critique.md \
  --report intermediate_zoom_out=docs/designs/reviews/intermediate.md \
  --report implementation_readiness=docs/designs/reviews/readiness.md \
  --approved-by 'Actual approver' \
  --approval-note 'Actual approval reference and accepted/resolved findings' \
  --output /tickets/TICKET-001-approved.json
python /tools/infra-code-factory/factory.py add --repo /project \
  --ticket /tickets/TICKET-001-approved.json
python /tools/infra-code-factory/factory.py run --repo /project
python /tools/infra-code-factory/factory.py run --repo /project --execute
```

A consolidated report may be supplied for all five stage paths if it actually
contains all five reviews. The handoff hashes the ticket, design and reports.
It refuses overwrites, uncommitted input, missing stages and missing approval.
The factory validates the binding at intake, before dispatch, after candidate
creation, during READY status evaluation, and before publication. It cannot
verify a human identity, the quality of report contents, or reviewer freshness
from Markdown; the receipt is an operator attestation under the existing trusted
local-controller model. No signing, remote approval authority or model evaluation
is implied. Never use fixture reports in production.

Changes to the design, reports or ticket scope require new review/approval and a
new handoff. Existing ledger tickets are immutable: create a replacement ticket
with `supersedes` where appropriate so attempt history is retained. No existing
code-review or cold-test requirement is removed by an EGM handoff.
