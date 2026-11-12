# Infra Code Factory 0.5.0 — EGM integration candidate

0.5.0 adds diff-selected specialist reviews, independent risk and human-review gates,
bounded repairs from pinned review/CI findings, and a live read-only ledger dashboard.
See [assurance and operations](docs/ASSURANCE_OPERATIONS.md) for configuration and commands.


0.4.2 adds durable versioned ticket holds, duplicate-safe intake, and a heading-matched
skill table of contents. See [ticket controls](docs/TICKET_CONTROLS.md) and
[the Machinist comparison](docs/MACHINIST_REVIEW.md).

0.4.1 added verified Matt Pocock/Superpowers skill inventories and conditional
builder helpers for Claude and Codex. See [SKILL_PROFILES.md](docs/SKILL_PROFILES.md).

0.4.0 added Google Elephant–Goldfish Model design handoffs, shared Claude/Codex workflow entries,
explicit provider/model configuration, and stronger route evidence validation.
Start with [EGM_WORKFLOW.md](docs/EGM_WORKFLOW.md) and [the current audit](docs/AUDIT_V040.md).
The original classic workflow remains available. See [CHANGELOG.md](CHANGELOG.md).

A desktop-led, local coding toolkit for Claude Code and Codex: one coordinator, two independent tickets, builder worktrees, independent cold repositories, executable checks, mandatory standards/spec plus policy-selected specialist reviews and guarded draft-PR publication. No automatic merge or deployment.

This is standalone Python source, not a globally installed skill. Download and extract the package into a stable tools directory outside your application repository. No pip dependencies. Python 3.10+, Git >= 2.29 and authenticated local coding CLIs are needed. GitHub CLI (`gh`) and authenticated Git push are needed for publishing; `gh` is also needed for GitHub CI repair.

**Validation boundary:** the included integration suite runs real Git worktrees with deterministic fake CLI workers/reviewers. This validates orchestration, transport and rejection cases. It does not prove real model quality or your local authentication. A real Claude/Codex pilot remains an onboarding step. The automated CI matrix covers Linux, macOS and Windows on Python 3.10 and 3.14; consult its actual results before relying on a platform. Local validation in this change is Linux only.

## Named evidence and failure controls

Checks must prove sensitivity to a deliberate defect in a separate checkout.
Reports enumerate named tests, and reviewers map each acceptance criterion to
observed test IDs. Existing count-only policies require migration and fresh runs.
See [configuration and migration](docs/NAMED_EVIDENCE.md).

Licensed under the [MIT License](LICENSE).

Unreleased local hardening addresses verification-wrapper protection, Git version
checks, UTF-8 text transport, platform path aliases and malformed CI responses.
See [audit follow-up](docs/LOCAL_HARDENING.md). Beyond a local pilot, the
[AUDIT.md production blockers](docs/AUDIT.md#production-release-blockers-and-required-acceptance)
require isolated identities, trusted signed verification and GitHub branch
protection with a merge queue; local checks do not replace them.

## Mandatory v0.3 setup

Read [HARDENING_SETUP.md](docs/HARDENING_SETUP.md) and [AUDIT.md](docs/AUDIT.md) first. v0.2 config/tickets are intentionally insufficient: a structured full-stack spec and verification policy are mandatory. Reviewers now run required checks in independent Git copies, using fresh CLI profiles and hashed test evidence. The steps below describe the original CLI lifecycle; the new setup guide supersedes its simple `checks` example and ticket schema.

The audit found a reproducible false-READY path in v0.2. v0.3 closes that local path but is **not production-certified**. Same-account code is not sandboxed; no automated merge or production revert is implemented.

## Quick installation into an existing project

Replace all example paths with actual local paths. Run in a terminal or ask your desktop coding agent to execute these steps.

1. Extract the toolkit to a stable directory, for example `/path/to/infra-code-factory`. On Windows use an absolute path such as `C:/Tools/infra-code-factory` and your installed `python` command.
2. Run `python --version`, `git --version`, `codex --version`, `claude --version`, and `gh auth status`. Authenticate missing tools through their normal local login flow. Do not paste credentials into tickets.
3. Open the application repository in Claude Code Desktop or Codex Desktop. Choose **one coordinator session**. Inspect existing `AGENTS.md`, `CLAUDE.md`, plugins, branch, uncommitted work, CI and test commands. Preserve user changes; use a clean setup branch/worktree if needed.
4. Preview and initialize:

```bash
python /path/to/infra-code-factory/factory.py init --repo /path/to/project
python /path/to/infra-code-factory/factory.py init --repo /path/to/project --apply
```

5. Locate the installed Superpowers `test-driven-development/SKILL.md`, retaining its reference files. Verify the seven primary skills in [SKILL_ROUTING.md](docs/SKILL_ROUTING.md). This session's Matt skills do not automatically exist on your desktop.
6. Preview and apply local CLI mappings:

```bash
python /path/to/infra-code-factory/configure.py --repo /path/to/project --tdd-skill /actual/path/test-driven-development/SKILL.md --provider codex --model YOUR_MODEL_ID
python /path/to/infra-code-factory/configure.py --repo /path/to/project --tdd-skill /actual/path/test-driven-development/SKILL.md --provider codex --model YOUR_MODEL_ID --apply
```

`configure.py` requires explicit provider/model selections and uses `agent_bridge.py`. Use `--provider claude --model YOUR_FULL_CLAUDE_MODEL_ID` for Claude, or per-role `--route` overrides. Add `--egm` to require approved design handoffs. It preserves checks, makes one backup, and refuses to overwrite an existing backup. Inspect the generated absolute paths and model access. It configures commands; it does not authenticate the providers.

7. Edit `.infra-factory/config.json`: set `base_ref` to your actual integration branch and `checks` to the real project's non-interactive check command arrays. Empty checks deliberately block execution. Each command runs from the worktree root; use an existing wrapper script for monorepo subdirectories or multi-step checks. Do not use watch-mode tests or start servers with fixed shared ports/databases. No shell interpretation is performed.

Example structure only—replace with commands from your repository:

```json
"checks": [
  ["python", "-m", "pytest", "-q"],
  ["npm", "run", "typecheck"],
  ["npm", "run", "build"]
]
```

Do not add checks for tools your project does not use. A zero-test discovery run is not adequate proof. On Windows, inspect executable resolution for `.cmd` tools; use a reviewed executable/wrapper compatible with `subprocess` rather than assuming Bash.

8. Review and commit only the intended setup files. Resolve/remove the configuration backup after review so the base checkout is clean. Integrate setup into the chosen base branch through your normal review process before ordinary ticket runs. The factory requires clean HEAD at `base_ref`; it does not stash, reset or clean your work.
9. Use the coordinator prompt below to create at least two meaningful independent tickets. Store the JSON ticket files outside the checkout or commit them before running. Add dependencies first.

```bash
python /path/to/infra-code-factory/factory.py add --repo /path/to/project --ticket /path/to/tickets/001.json
python /path/to/infra-code-factory/factory.py add --repo /path/to/project --ticket /path/to/tickets/002.json
python /path/to/infra-code-factory/factory.py run --repo /path/to/project
python /path/to/infra-code-factory/factory.py run --repo /path/to/project --execute --limit 2
python /path/to/infra-code-factory/factory.py status --repo /path/to/project
```

The preview shows which tickets can run and, under `waiting`, why each other ticket cannot. Two independent tickets run together; unmerged dependencies wait, and so does any ticket whose paths overlap another ticket in the batch or a READY or AWAITING_HUMAN candidate that has not been merged or rejected. The coordinator must also judge semantic dependencies not detectable from paths.

10. For each READY ticket, inspect the recorded checks, both reviews and diff. Preview publication, then explicitly publish a draft:

```bash
python /path/to/infra-code-factory/factory.py publish --repo /path/to/project --ticket TICKET-001
python /path/to/infra-code-factory/factory.py publish --repo /path/to/project --ticket TICKET-001 --execute
```

Publication revalidates candidate/config/base/reviews and recorded test artifacts, and checks the remote base. It reuses the recorded cold-test results; it does not rerun the test commands. It pushes the reviewed commit and creates or reuses its draft PR. It never merges. A network, authentication or CLI failure leaves the ticket READY with an `error` note: fix the transport and rerun `publish`. A candidate, evidence or remote-base mismatch revokes READY. Remote CI still needs to complete before human merge.

## Start a project from scratch

1. Describe the product, users and a real successful user journey to the coordinator. Use Matt `grill-me` to resolve consequential choices, `to-spec` to capture the agreed design, and `to-tickets` to produce vertical slices.
2. Select the stack from the product needs, not from this toolkit. Establish a minimal runnable skeleton, dependency lockfiles, initial automated behavior test and Git repository with an initial commit. This shared foundation is a prerequisite; do not pretend two dependent setup tickets are independent.
3. Apply the installation/configuration steps above. Set real checks and commit the setup.
4. Select two independent vertical tickets, each containing its implementation and tests with nonoverlapping owned paths. Run the preview, then the two-ticket pilot. Verify outcomes in the running application as well as tests.
5. Publish reviewed drafts. Human merge remains separate; dependent work starts only once its prerequisite changes are present in the chosen base.

For a disposable Python learning pilot, initialize a Git repository with README and `.gitignore` containing `__pycache__/`. Use the two JSON tickets under `examples/`. Configure a unittest discovery command that asserts at least one test was collected. Each candidate will include its own module and tests. These sample tickets are not intended for ContraClaim or Vanshavali.

## Classic coordinator prompt

For the EGM alternative, read `skills/infra-factory/SKILL.md` and follow
[EGM_WORKFLOW.md](docs/EGM_WORKFLOW.md); it replaces the classic interview/design
stages below. The two post-implementation code-review lenses remain required.

```text
Read /path/to/infra-code-factory/docs/DESIGN.md, SKILL_ROUTING.md,
and MODELS_AND_AGENTS.md. You are the only coordinator for this project.
Inspect repository instructions, actual installed skills, current Git state,
and available CLI models. Use only the predefined primary skill for each stage.

Grill me only on unresolved consequential requirements. Reuse settled decisions.
Turn the agreed design into a specification and vertical JSON tickets with
acceptance criteria, owned paths and dependencies. Allocate at most two
independent tickets at a time through factory.py. Do not create fake independence
by splitting a shared migration, auth change or generated interface.

Builders and reviewer leaves do not allocate agents. Track all work in the
factory ledger. Diagnose failures before retrying. Require actual checks and
both independent review lenses at the exact candidate. Publish reviewed draft
PRs within my authorized scope. Never merge or deploy automatically.
Keep me informed of completed work, blockers, evidence and the next allocation.
```

For an existing project append: “Preserve its architecture and current work. Read the relevant audit and source code, reproduce the selected defect, and do not restart settled design.”

For a new project append: “Begin with the product interview and a minimal runnable foundation, then choose two independent vertical slices.”

## Ticket format

See `examples/DEMO-001.json` and `DEMO-002.json`. Required fields: `id`, `title`, `description`, nonempty `acceptance`, literal relative `paths`, `depends_on`, `role` (`backend`, `frontend`, `critical`), and `spec` with exactly the sections `ui`, `api`, `data` and `cross_cutting`, each either `{impact, acceptance}` or `{not_applicable}`. Paths may be files or directories; use forward slashes. Glob patterns and traversal are rejected. A ticket's scope must cover its tests as well as implementation. Existing IDs are not overwritten.

## Tracking, recovery and limits

Each CLI invocation records minimal local start/finish metadata, including
previews and failures, in a separate `usage.sqlite3` store. No prompts or
credentials are collected and nothing is uploaded. See
[local usage tracing](docs/USAGE_TRACING.md) for inspection and limits.

Use `hold` / `release` to pause inactive tickets durably, and `add --idempotent`
when repeating an identical submission after a lost response. See
[TICKET_CONTROLS.md](docs/TICKET_CONTROLS.md) for version checks and examples.
Use `intake` or `link-issue` to retain GitHub Issue provenance locally; see
[Issue intake](docs/ISSUE_INTAKE.md) for previews, duplicate handling and PR links.

- SQLite ledger, prompts, logs, candidate branches and reviewer worktrees live under the Git common directory's `infra-factory/`. This is local durable state, not GitHub backup. Back it up through your normal local backup process; do not publish private prompts/logs blindly.
- `status` shows recorded state and evidence. READY is a historical local result; `publish` performs current eligibility checks. It is not a production-readiness certificate.
- The coordinator lock prevents two local runners from allocating simultaneously. An editor, another OS account or another machine is outside this lock's scope.
- `retry --repo PATH --ticket ID` requeues a BLOCKED task after the coordinator diagnoses the failure. It retains old evidence, creates a fresh worktree on the next run, and permits at most three total attempts. It does not restart a running task.
- `unlock --repo PATH` removes a `coordinator.lock` left by a killed controller when no ticket is in flight. It refuses unless the recorded owner is a dead process on this machine.
- Ctrl-C or SIGTERM kills the agents and checks the controller started, releases the lock and marks in-flight tickets BLOCKED (this counts as an attempt).
- `recover --repo PATH --ticket ID` handles a stale RUNNING/REVIEWING task only after its local owner is confirmed gone. It does not kill unknown processes or delete retained work.
- Worktrees are retained for inspection and recovery. Clean them through normal reviewed Git worktree cleanup after delivery; the toolkit does not perform destructive automatic cleanup.
- A dependency is recognized as merged only when its exact candidate is an ancestor of the current base. Squash/rebase merges change identity and need explicit reconciliation; do not edit the ledger to fabricate success. Prefer a merge preserving candidate ancestry for this initial version, or create a newly reviewed ticket with dependencies resolved against the new base.
- Whole-project CI, protected-branch settings and production deployment remain your project's responsibility. Local worktrees are not a security isolation boundary.

## Test the toolkit

```bash
python -m unittest discover -s /path/to/infra-code-factory/tests -v
```

Tests create disposable repositories; they do not call paid model providers or publish to GitHub. See [current validation](docs/VALIDATION_CURRENT.md) for executed results and limits.

## Further reading

- [Decision contract](docs/DESIGN.md)
- [Seven-skill registry](docs/SKILL_ROUTING.md)
- [Model and agent allocation](docs/MODELS_AND_AGENTS.md)
- [Karpathy: source-grounded design interpretation](docs/KARPATHY.md)
