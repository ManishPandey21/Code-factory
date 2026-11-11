# Audit of Infra Code Factory v0.3.4 and v0.4.0 changes

Audited 11 November 2026. Input: `infra-code-factory-v0.3.4.zip`, all 30 listed
SHA256SUMS entries verified. The original 131 tests passed on Linux, Python
3.12.14 and Git 2.52.0. This is a local code/behavior audit, not a certification.
Archive claims and instruction documents were treated as source material.

## Findings and disposition

| Priority | Finding / evidence | Disposition |
|---|---|---|
| High | `factory.routing_evidence` accepted any JSON object with `outcome: ok`, even when its provider, model and effort disagreed with configuration. Reproduced with a wrong-model receipt. | Fixed: strict receipt schema/exit code/identity validation; regression rejects each mismatch. |
| High usability | `configure.py` silently generated seven routes using hard-coded model IDs. Account availability was never established; using only Codex required seven overrides. | Fixed: explicit provider/model selection fills all roles, with optional per-role overrides. Existing configuration remains readable. No availability claim is made. |
| Medium | Controller discarded Codex's `served_models_verified: false`, obscuring the adapter's stated limitation. | Fixed: preserve it in routing evidence summaries; successful Claude usage check sets it true. |
| High workflow gap | Existing “cold” code reviews were not Google's EGM design-review workflow. No approved design or review report was bound to implementation tickets. | Added native EGM host workflow plus artifact/ticket hashes enforced throughout factory lifecycle. This is an imported approval attestation, not authenticated human identity. |
| Medium | CLI integration tests used deterministic stand-ins. No current real Claude compatibility or authentication was proven. | Still open: run a controlled live pilot on each intended CLI/account before adoption. Codex 0.167.0-alpha.4 help was inspected; Claude is absent here. |
| Medium | `check_served` uses aggregate token dominance: a secondary model with fewer or equal output tokens can coexist with the requested one. That does not prove every final-answer token came from the pinned model. | Still open: define a strict single-model policy or validate final-message model identity where supported; label aggregate usage evidence accurately. |
| Medium | Reviewer OAuth refresh uses read/compare followed by `os.replace`; concurrent processes can race between those operations. | Still open: use dedicated reviewer authentication or an interprocess credential-refresh lock. Do not treat the existing comparison as atomic. |
| Medium | Cold check environments remove proxies/CA variables and start without installed project dependencies. Real dependency-backed verification needs a supported bootstrap/cache/service strategy. | Still open: explicit trusted runtime configuration, dependency installation and per-run service namespaces; retain credential isolation and TLS verification. |
| Medium | Routing files are recorded with hashes, but their hashes are not part of `check_evidence_files`' cold artifact map. Post-READY routing-file tampering is not independently rechecked at publication. | Still open: include routing receipts in the publication evidence envelope, with builder and reviewer identity binding. |

## EGM design decisions

Use Google's complete native plugin for brainstorming, drafting, five-stage
Goldfish design review, resolving findings and drift reporting. Keep the factory
as the implementation allocator; do not run two competing allocators. EGM's
comprehension stage must see only the document, not the Elephant's history.
The existing two code-review lenses and cold-test policy remain mandatory.

The handoff requires committed local design/report artifacts, all five stage
keys, explicit approval attribution/disposition, and the exact normalized ticket
hash. A consolidated report can cover all stages. The controller checks bytes
and scope, not semantic report truth. An operator can fabricate an attestation;
stronger approval needs an authenticated service outside the worker's authority.
No local file format can prove a human approved it or that a model started fresh.

## Independent review of this change

Standards/correctness review found a malformed-ticket CLI diagnostic issue:
`FactoryError` escaped the handoff command's normal error handler. It is now
translated to the normal concise error, with a CLI regression test.

Requirement review found that code reviewers were not explicitly instructed to
read the approved EGM design, and that the legacy skill-routing guide could
conflict with EGM. Both are corrected: each code-review lens reads applicable
design constraints independently, without using prior EGM review conclusions;
the guide now distinguishes EGM from classic planning stages. Prompt assertions
cover the design instruction. A first targeted rerun exposed the fixture's
requirement for a terminal JSON evidence block; the extra instruction now
precedes that block, preserving its format.

Both independent reviewers rechecked their fixes and reported no remaining
issues within that follow-up scope. This does not close the pre-existing
limitations listed above.

The README also overstated publication behavior: the implementation rechecks
recorded evidence rather than rerunning tests. The wording now matches the code.

## Recommended next improvements

1. Exercise one small real project on Claude and Codex, including auth refresh,
   permission denial, test installation, failure recovery and draft publication.
2. Bind all routing receipts into the same verified publication envelope and
   test tampering between READY and publish.
3. Run untrusted builders/checks under separate identities or isolated runners;
   protect the ledger and approval authority from same-account writes.
4. Add credential refresh locking and a supported dependency/service bootstrap.
5. Add CLI-version compatibility checks and measurable per-role cost/quality
   evaluation before recommending default model families.
6. Enforce remote branch protections/merge queue for production delivery. Local
   READY and EGM approval are not server-side merge protection.

## Verification

Original baseline: 131 tests passed in 201.102 seconds. Targeted tests for
provider configuration, routing identity and EGM handoff passed. The EGM test
runs real Git repositories and the real handoff/add/run/status/publish paths;
workers remain deterministic fixtures. See `VALIDATION_V040.md` for final totals.
No live EGM reviewer run or paid provider execution is claimed.
