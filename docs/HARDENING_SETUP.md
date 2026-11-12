# Install and migrate to v0.3

For the current named-report schema and mandatory negative controls, also follow
[NAMED_EVIDENCE.md](NAMED_EVIDENCE.md). The historical steps below remain the base setup.

This is a breaking, fail-closed local hardening candidate. Preserve v0.2 evidence; do not copy old READY receipts into new runs. Existing v0.2 queued tickets need the new spec fields. A v0.2 config's empty verification policy is not eligible. Do not alter live ledger records to fabricate migration success: use new scoped ticket IDs after setup.

## Existing application

1. Require Python 3.10+ and Git >= 2.29 (`git --version`); the controller and cold checkout helper reject older Git before work. Extract the toolkit outside the application repository. Run `python -m unittest discover -s /absolute/infra-code-factory/tests -v`.
2. In a clean setup branch, retain existing AGENTS.md/CLAUDE.md. Run factory.py init --repo PROJECT --apply; it preserves existing config. Run configure.py with the installed TDD skill path if CLI mappings need setup. It preserves verification policy and makes one backup.
3. Keep checks for project build/lint/typecheck commands; these now run in each cold clone. Add verification from examples/verification-policy.json, replacing every absolute tool path and project suite command. Configure each report adapter against actual native test output. Missing categories, missing dependencies, reports or tests block; do not replace them with successful no-ops.
4. Map actual path roots to frontend/backend/shared, including nested apps/packages. Unknown/shared or both-stack impact selects full-stack plus contract checks. Optional required categories can strengthen minima (security/migration/accessibility via project-supported suite categories), never weaken them. All layers require explicit roots; nonexistent roots are fine for absent layers, but paths outside the real mappings conservatively trigger all suites.
5. Add `.factory-test-output/` to the project's .gitignore during trusted setup. This holds native JUnit XML. Normalized reports and hashes live outside candidate source. Install dependencies reproducibly into each fresh checkout via reviewed external wrappers; no builder node_modules, virtualenv or ambient credentials are reused. Use ephemeral databases/ports keyed by FACTORY_NAMESPACE. No production connection strings are inherited by checks.
6. In-repo paths directly referenced by any checks/verification argv are automatically protected, including directory descendants and deleted wrappers. Add indirect wrapper/helper paths to protected_paths; prefer wrappers and holdout tests outside candidate write scope. Existing test edits/deletions, runner configs/manifests, symlink/submodule repositories require separate policy maintenance or a stronger isolated runner. This conservative restriction is deliberate.
7. Commit reviewed setup on the integration base. Set commands for the actual available model IDs. Reviewer profiles copy only provider authentication files/tokens, not settings/plugins/history; Claude keychain-only authentication may need a dedicated verifier login. No live-auth pilot has been performed here.
8. Write tickets with required spec sections (see examples). Top-level and layer acceptance items are all reviewed. Add two genuinely independent tickets; preview then run:

```bash
python /absolute/infra-code-factory/factory.py add --repo PROJECT --ticket /absolute/TICKET-1.json
python /absolute/infra-code-factory/factory.py add --repo PROJECT --ticket /absolute/TICKET-2.json
python /absolute/infra-code-factory/factory.py run --repo PROJECT
python /absolute/infra-code-factory/factory.py run --repo PROJECT --execute --limit 2
python /absolute/infra-code-factory/factory.py status --repo PROJECT
python /absolute/infra-code-factory/factory.py publish --repo PROJECT --ticket TICKET-1
python /absolute/infra-code-factory/factory.py publish --repo PROJECT --ticket TICKET-1 --execute
```

Keep published output as a draft pending protected server verification. A recorded READY is historical; inspect verification_current and use publish's current gate. After a base merge, recreate/review the next candidate against the new base; do not reuse its previous verdict.

## New application

Interview the product owner with the existing Matt Pocock requirements workflow, then create the technical specification and dependency-linked tickets. Establish a minimal Git repository, runnable frontend/backend skeleton, dependency lockfiles and real test harness as one foundation change. Configure the trusted policy above. Only then allocate two independent vertical feature tickets. Do not turn missing tests into N/A to get a green pipeline. A genuinely backend-only application needs a policy adapted explicitly by its owner; the full-stack sample is intentionally strict.

## Failure and rejection

```bash
python /absolute/infra-code-factory/factory.py retry --repo PROJECT --ticket TICKET-1
python /absolute/infra-code-factory/factory.py reject --repo PROJECT --ticket TICKET-1
```

Retry requires BLOCKED and fewer than three attempts. Reject applies to inactive, unmerged candidates; retains files/evidence, does not close a remote draft, delete a branch or reset main. Close a published failed draft through normal GitHub review. Recovery does not prove orphan processes exited; inspect and isolate them before reusing external test resources.

## Evidence and limits

Per-lens manifest.json includes exact base/head/tree, ticket/config hashes, test commands, named passing/failing outcomes, mutation receipts, changed paths, acceptance-to-test mappings, direct tool hashes and SHA256 for the binary diff/logs/reports. No signatures or external trust root are provided. Logs can contain application test data; protect access and configure external retention. Native browser traces/screenshots should be retained by the project's trusted wrapper and verified in CI; the generic JUnit adapter does not certify pixels or capture browser evidence by itself.

Read AUDIT.md before any unattended production use. Automatic merge/deploy and autonomous production rollback remain unsupported.

See [LOCAL_HARDENING.md](LOCAL_HARDENING.md) for exact path recognition, UTF-8 and trusted-root handling, plus remaining production release blockers.
