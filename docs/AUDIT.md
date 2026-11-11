# Infra Code Factory v0.2 audit and v0.3 hardening candidate

Date: 10 November 2026. Outcome: **PARTIAL — hardened local verification; autonomous high-stakes production operation is not established.**

Scope: all delivered Python source, CLI bridge/configurator, fixtures, tests, examples and documentation. Original v0.2 is the local Git baseline. This is the downloaded toolkit, not a newly published GitHub repository. Three reference implementations were reviewed at selected source files; see REFERENCE_AUDIT.md. No production application or deployment was modified.

## Diagnosis and disposition

| Finding | Severity | v0.3 disposition and evidence |
|---|---|---|
| Checks ran only in builder workspace; ignored artifacts could produce false READY | Critical | Fixed: fresh independent object fetch/checkout per cold lens; preliminary checks rerun there. Regression deliberately supplies builder-only ignored flag and requires BLOCKED. |
| Reviewers did not receive or confirm executable evidence | Critical | Fixed locally: independent test executions, report/log/diff hashes, exact base/head/tree/policy/ticket identity; PASS requires evidence digest, complete file and acceptance coverage. |
| Shared Git state, home, history and memory | Critical | Reduced: separate reviewer repositories, ephemeral profile, no copied history/settings/plugins, filtered check environment. **OS boundary still absent**; arbitrary same-user code can access controller state and other files. |
| Any successful argv/no-op could satisfy test gate | High | Fixed structural gap: mandatory categories, nonempty native JUnit tests, no skips/errors/failures. Reporter honesty and category correctness remain trusted project inputs. |
| Spec omitted full-stack impact | High | Required UI/API/data/cross-cutting impact and criteria or explicit N/A; review covers all criteria. Semantic completeness still depends on requirements work and review, not a JSON schema. |
| Builder could weaken tests/config | High | Existing test edits/deletions and known runner/manifests/config edits are refused; additional protected_paths supported. New tests allowed. Generic heuristic is not exhaustive; external trusted policy/runner required for strong enforcement. |
| External script/skill changed after review | High | Direct executable/script/skill bytes are hashed and checked at completion/publication. Transitive packages, system libraries, images and network services are not fully pinned. |
| Stale or altered evidence accepted | High | Evidence digests and artifact bytes rechecked before publication; candidate/base/config identity checked. Local evidence is unsigned and same-account mutable, not adversarial attestation. |
| Failed publication retained READY | High | Executed publication failures revoke READY to BLOCKED, including initial eligibility failures. Status exposes verification_current; dry runs do not mutate state. |
| Two path-disjoint tickets may interact | High | Builders still overlap; cold test phases serialize locally. Both-stack/shared/unknown scope requires contract checks. After first merge, second candidate's base is stale and must be rebuilt/reviewed. Semantic independence and external resource isolation remain project responsibilities. |
| Automatic merge/revert missing | High | **Still not implemented.** No unsafe substitute added. reject records REJECTED and preserves base/evidence; this is rejection of unmerged work, not production rollback. |
| Intake/spec creation is prompt-driven | Medium | Strict ticket ingestion is implemented; autonomous GitHub issue watcher, spec writer and semantic approval are not implemented. Coordinator interview/spec/ticket workflow remains required. |
| Git operations unbounded | Medium | Main Git helper/status and cold Git operations bounded; agent/check process timeouts retained. Some direct legacy calls and interrupted descendant recovery still need deployment hardening. |
| Limited observability | Medium | Transactional state-transition events added; per-attempt reports/diff/logs retained. No signed remote event sink, retention quota, alerts or distributed lease. |
| Test evidence synthetic | High readiness limit | Factory orchestration uses real Git/processes with fake models and synthetic policy counts. JUnit parser runs real subprocess fixtures. No real target frontend/browser/backend suite or provider/GitHub pilot executed. |

Independent final review found two additional regressions during hardening: optimized Python removed status assertions, and examples lacked the new spec. Both were corrected, with independently passing targeted regressions. Final suite: **81 passed**; see VALIDATION.md.

## Enforced local flow

1. Coordinator supplies an explicit ticket/spec and centrally maintained verification policy. Missing data fails before dispatch.
2. Builder receives original ticket in its allocated worktree, with no publication authority in the prompt. This prompt is not an OS credential boundary.
3. Controller validates scope, verification-sensitive paths and one-commit ancestry; candidate is pinned.
4. Each of two cold lenses gets an independent repository with no builder ignored files, copied Git config/hooks, branches or transcript files. It receives the original ticket, pinned diff and controller-produced test evidence, never the builder's explanation.
5. Required test categories run in fresh cold state. Both lenses independently rerun the selected checks. One local verification lock avoids overlapping test execution. Environment includes FACTORY_NAMESPACE for project wrappers to provision isolated test services.
6. Native test reports must contain real testcase entries and show all passing with zero skips. Each verifier must confirm all files and all top-level/layer acceptance criteria, plus tests, against the evidence digest.
7. Only matching PASS results can yield local READY. Draft publication checks identities and artifacts again. Draft body explicitly says LOCAL verification; no server check named “verified” is forged.
8. Rejection/failure leaves integration base untouched and retains evidence. A retry is a fresh candidate and review, bounded to three attempts.

## What the local guarantee means

Under a trusted local controller, trusted reporters and honest filesystem/process boundaries, a factory-created draft cannot pass the publication gate without both cold reviewers confirming the complete configured test evidence for the exact candidate and reviewed base. The system cannot prove that every *relevant* test exists, that a visual suite really exercises visual regressions, or that arbitrary same-user code has not forged controller state. A model echoing coverage fields is not a mathematical proof of review quality.

Therefore the requested absolute guarantee—no code can become mergeable without independent full-stack verification—**is not established by this local toolkit**. GitHub may call a branch mergeable even while the factory blocks it. Draft status is not branch protection. No production-grade certification is claimed.

## Production release blockers and required acceptance

1. **Separate runtime identities.** Builder, tests, verifier and controller must run in isolated containers/VMs/accounts. No builder mount of ledger, credentials, reviewer history or holdout suites. Read-only source input for verifier; narrowly controlled evidence output; no inherited production secrets. Test network/volume/CPU/memory/process limits and forced teardown.
2. **Trusted verification service.** Pin runtime images, lockfiles, test harness and holdout policy outside candidate control. Sign receipts bound to repository, base/head/merge-group SHA, spec/policy/toolchain digest, suite outputs and expiry. Reject absent, stale, skipped, cancelled or wrong-app checks.
3. **Server merge boundary.** Repository ruleset requires current trusted verifier App checks and protected CI, disallows bypass/force pushes and unauthorized ready/merge, and uses a merge queue testing the combined candidate. Bind merge to exact head/current target. Review again when base changes. Local CLI permissions alone are insufficient.
4. **Project-specific proof.** Supply real frontend unit/component/visual/e2e/accessibility and backend unit/API/integration/contract/security/migration tests. Test loading/empty/error/mobile states, tenant and permission boundaries, concurrent writes, backwards compatibility and migration recovery. Prove selected regression tests fail for the intended behavior before the fix.
5. **Release/rollback contract.** An unmerged failed candidate is discarded logically, not reverted on main. A merged regression requires a new revert candidate with fresh verification; database/external side effects require tested compensating actions and backups. Never reset shared main automatically.
6. **Operational pilot.** Authenticate actual CLI versions in isolated profiles; exercise two independent tickets, failure/timeouts, process death/orphans, evidence tampering, remote-base movement, network interruption and merge queue. Verify logs/alerts/retention and resource isolation. Windows/macOS behavior remains untested.

These are engineering/deployment blockers, not a request for permission to complete reversible local work. No external target repository or protected runner was configured in this session.
