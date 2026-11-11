# Reference implementation review — 10 November 2026

Scope: selected current source files from the three requested repositories, retrieved through GitHub. This is a design comparison, not a full security audit or execution of those projects. No upstream source code was copied into Infra Code Factory. Tree identities below identify the observed repository trees; individual files were retrieved from `main`, so these are not an atomic repository snapshot.

| Repository | Observed tree SHA | Useful mechanism | Important limit |
|---|---|---|---|
| addyosmani/factory | `8af116567166a0a16588b7ab1b9934ece0b775bc` | Cold diff review, verifier reruns gates, regression test counterfactual, missing required checks fail | Prompt/hook controls are not OS isolation or a server merge boundary; full-stack test selection needs project policy |
| zazencodes/zazencodes-season-3, v2 subtree | `5fc7c983f44d623057ef65361f25cf23cab2abef` | Structured intake/spec/build/review/approve states, UI/UX review routing, checks script from trusted main checkout | Merge updates candidate after review and reruns checks without a fresh review; verdict files lack exact head binding |
| coleam00/ai-software-factory | `f6d8f69e452607ceedc6d42f2ed0398db543ba71` | Runtime snapshot identity, isolated state, separate holdout role, workflow source pin | Main workflow/merge implementation is delegated to Archon; ordinary checks can accept unknown test count |

## Addy Osmani

[Cold verifier](https://github.com/addyosmani/factory/blob/main/template/.claude/agents/factory-verifier.md) tells the reviewer to ignore the implementer's narrative, read every changed hunk, independently rerun the gates, test the new regression test without the fix, and reject unattended edits to existing tests. It rejects load-bearing paths, so it does not itself authorize autonomous high-stakes changes.

[gates.sh](https://github.com/addyosmani/factory/blob/main/template/.claude/scripts/gates.sh) distinguishes GREEN, RED, and MISCONFIGURED; required checks skipped because tools/scripts are absent yield nonzero status. Stack autodetection chooses a single root stack, so a Python backend plus nested React frontend still needs explicit project adaptation. Defaults do not inherently require e2e, component, visual, API contract, migration, or accessibility tests.

[prove-test.sh](https://github.com/addyosmani/factory/blob/main/template/.factory/scripts/prove-test.sh) reverses non-test changes and requires the focused test command to fail, then restores the patch. This is useful sensitivity evidence; a nonzero result alone does not distinguish the intended assertion from an environment/import failure.

[block-merge.sh](https://github.com/addyosmani/factory/blob/main/template/.claude/hooks/block-merge.sh) explicitly calls its shell matching defense in depth and says GitHub rulesets must enforce the real boundary. Its model remains human merge. Adopt fail-closed gates and independent test sensitivity, not a claim that local hooks prevent every bypass.

## ZazenCodes v2

[spec-writer](https://github.com/zazencodes/zazencodes-season-3/blob/main/src/software-factory-claude-code-v2/.claude/agents/spec-writer.md) requires actual code discovery, numbered observable criteria, verification methods, scope, and explicit assumptions. [UI reviewer](https://github.com/zazencodes/zazencodes-season-3/blob/main/src/software-factory-claude-code-v2/.claude/agents/reviewer-ui.md) uses separate browser sessions and desktop/mobile screenshots, but reads `build.md` and previous reviews: it is a specialized reviewer, not strictly a cold verifier without builder narrative.

[gate](https://github.com/zazencodes/zazencodes-season-3/blob/main/src/software-factory-claude-code-v2/factory/bin/gate) runs the main checkout's checks script inside the candidate and writes the candidate commit to checks.md. It guards modifications/deletions to configured protected files but explicitly allows additions. The checks can still invoke candidate-owned scripts. The call has no subprocess timeout in this file.

[job](https://github.com/zazencodes/zazencodes-season-3/blob/main/src/software-factory-claude-code-v2/factory/bin/job) validates the gate commit before entering review. Review acceptance subsequently parses first-line verdicts. In `cmd_merge`, it fetches/merges latest base into the branch, reruns the gate, pushes, marks ready, and calls `gh pr merge` without `--match-head-commit`. No new reviewer call after that merge is visible in this function. This does **not** establish that the final merged diff received independent exact-head review. An inability to merge escalates rather than reverting production.

[approver](https://github.com/zazencodes/zazencodes-season-3/blob/main/src/software-factory-claude-code-v2/.claude/agents/approver.md) explicitly escalates auth/permissions, money, deployment/CI, migrations, dependencies, and production writes. Its policy therefore differs materially from unrestricted autonomous infrastructure changes.

## Cole Medin / Archon consumer

[pack.json](https://github.com/coleam00/ai-software-factory/blob/main/template/factory/pack.json) pins Archon integration revision `1cfb8fc541580fe5edf15e9a504b572bc9bb45bb`; [consumer.py](https://github.com/coleam00/ai-software-factory/blob/main/template/factory/consumer.py) delegates workflow decisions to that source. The actual Archon merge queue was not audited in this review, so its guarantees cannot be inferred merely from this wrapper.

[WORKFLOW_POLICY.md](https://github.com/coleam00/ai-software-factory/blob/main/template/factory/WORKFLOW_POLICY.md) requires current-source runtime/holdout identity and independent current-head review. [runtime_host.py](https://github.com/coleam00/ai-software-factory/blob/main/template/factory/runtime_host.py) implements source copying and digest checks, fresh per-attempt state, environment filtering, finite readiness timeouts, health and build identity endpoints, and teardown on failure. This is substantially stronger runtime evidence than running tests in the builder checkout. It remains a local process host, not a hostile-code security sandbox.

[ci.py](https://github.com/coleam00/ai-software-factory/blob/main/template/harness/ci.py) fails timeouts, absent static+unit configuration, and zero tests when `unit_count_pattern` is configured. With no pattern, it explicitly emits `tests=unknown` and continues; ordinary checks alone are not runtime verification.

[holdout_fence.py](https://github.com/coleam00/ai-software-factory/blob/main/template/.factory/hooks/holdout_fence.py) restricts tool access by agent role and records observed exposures. It is useful application-level separation, but lexical command filtering cannot establish OS-level secrecy against arbitrary code under the same user account.

## Recommended synthesis

Use one deterministic coordinator, trusted versioned specification and impact policy, a disposable builder environment, independently executed full-stack checks from a fresh candidate snapshot, and cold full-diff review tied to base/head/spec/policy/evidence digests. Missing categories, unknown tests, skipped required checks, stale review, mutable test policy, or inconclusive findings must block. Separate deployment rollback from rejecting an unmerged candidate. Only a server-enforced merge gate with restricted credentials and current integration checks can make local verification a real merge boundary.
