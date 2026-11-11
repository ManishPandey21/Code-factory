> Historical v0.2 design. v0.3 changes and current limitations are authoritative in AUDIT.md and HARDENING_SETUP.md. The latest request sought autonomous merge/revert; those remain blocked by missing runtime/server enforcement, not by the earlier user preference.

# Infra Code Factory 0.2 — decision contract

10 November 2026. This supersedes the one-ticket prototype described in Infra_Code_Factory_Review.md.

## Confirmed decisions

The owner selected: two independent tickets in parallel; local CLI workers launched from a desktop coding session; reviewed draft PR delivery. No automatic merge or deployment. One coordinator owns assignments and the ledger. No nested worker orchestration. Skill selection is predefined by job type, not improvised from the entire installed catalogue.

## User stories

1. As an owner, I want a focused requirements interview so that unsettled product choices are resolved before coding.
2. As an owner, I want a specification and dependency-linked vertical tickets so that completion is measurable.
3. As an owner, I want two independent tickets to progress concurrently so that parallel work saves time without colliding.
4. As a coordinator, I want a durable single-writer task ledger so that sessions can resume without duplicate allocation.
5. As a worker, I want a bounded task, selected skill, model, worktree and acceptance criteria so that I can implement without guessing scope.
6. As a reviewer, I want the original requirements and a pinned diff so that I can judge work independently.
7. As an owner, I want failures, missing checks and stale results to stop delivery so that plausible summaries cannot substitute for evidence.
8. As an owner, I want installation to preserve existing instructions and changes so that an active project remains intact.
9. As an owner, I want separate new-project and existing-project setup steps so that the factory is useful in both cases.
10. As an owner, I want transparent model and skill configuration so that my installed tools and subscriptions determine what can actually run.

## Flow

Intake/discovery → grill unresolved decisions → approved specification → vertical tickets with dependencies and owned paths → coordinator validates readiness → up to two independent builders in separate worktrees → required executable checks → candidate commit → fresh spec and standards review → delivery eligibility → draft PR, when published through the documented delivery step.

Any failing or inconclusive stage blocks the ticket. A new candidate invalidates earlier evidence. Dependent tickets must not start merely because a prerequisite is reviewed: its changes must be present in their base. Path isolation does not prove semantic independence; the coordinator checks API, schema, shared state, migration and port/database dependencies before dispatch. Shared migrations, auth policies, generated contracts and global lockfiles are normally serialized.

The coordinator is the human-facing Claude/Codex session plus the deterministic local runner. The session decides product intent and ticket scope. The runner enforces queue ownership, worktree allocation, check execution and ledger changes. The runner itself is not an LLM or an autonomous product manager.

## Boundaries

No automatic skill downloads, model switching, installing dependencies, bypassing permissions, production mutation, provider API service, distributed fleet, browser UI, unattended daemon or unconditional merge. CLI processes share the local OS account: worktrees are collision prevention, not security sandboxes. Agent instructions are policy; host permissions and GitHub protections are enforcement.

Initial integration validation uses real Git worktrees and deterministic fake worker/reviewer processes. It proves coordination and failure handling, not Claude/Codex intelligence or local authentication. Real two-provider execution needs an onboarding pilot on the owner's computer.

## Engineering tickets for acceptance

The downloadable examples form two independent vertical test tickets rather than two halves of the factory internals:

- DEMO-001: add a small greeting module and its behavior test, limited to its own two files.
- DEMO-002: add a subtotal module and its behavior test, limited to its own two files.

Each must traverse allocation, independent worktree, implementation, checks, commit and review. The validation suite should establish actual temporal overlap and independent candidates, then deliberately inject conflicts and failures.
