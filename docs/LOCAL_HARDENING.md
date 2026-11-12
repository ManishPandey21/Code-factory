# Local pilot hardening: audit follow-up

These changes address M2 and L1–L4, plus the narrow L5/L8 and display fixes below.
They do not satisfy the [production release blockers in AUDIT.md](AUDIT.md#production-release-blockers-and-required-acceptance).

## Verification inputs (M2)

The controller automatically protects in-repository files and directories directly
named by any `checks` or `verification.checks[].argv`, across every configured
suite. Protection is checked before cold tests and rechecked before approval,
repair and publication. Both base and candidate Git trees are inspected so
additions, deletions and rename source paths cannot evade it.

Recognized forms include `scripts/run_checks.sh`, `./scripts/run_checks.sh`,
`{worktree}/scripts/run_checks.sh`, absolute paths into the source checkout,
`--config=ci/settings.json` and pytest `path.py::test_name` selectors. A referenced
directory protects its descendants; referencing `.` protects the entire tree.
Changes to these inputs need a separate policy-maintenance workflow. The rule
does not silently modify project config or its `protected_paths` list.

This is direct argv path recognition, not interpretation of shell/Python source,
package script names, module imports or dynamically generated paths. Keep
`protected_paths` for indirect wrappers, imported helpers, holdout suites and
other project-specific inputs. Prefer externally controlled verification tools.
Protecting known paths does not establish an adversarial runtime boundary.

## Git requirement (L1)

Python 3.10+ and **Git 2.29 or later** are required. The controller checks
`git --version` before repository work; standalone cold-checkout creation checks
before allocating a destination. Older, missing or unrecognized Git versions
produce a clear error. Apple Git and Git for Windows version suffixes are accepted.
Git 2.29 is needed for `init --object-format` and `fetch --no-write-fetch-head`.
Check the executable actually on the coordinator's PATH with `git --version`.

## Text and paths (L3/L4)

Text file I/O and text subprocess pipes explicitly use UTF-8, including configs,
tickets, prompts, reviews, manifests, PR bodies and fixture I/O. Binary evidence,
raw process logs and native XML remain bytes; XML honors its declared encoding.
A regression runs non-ASCII prompt transport with Python UTF-8 mode disabled in
an ASCII locale.

Path checks first resolve the explicitly trusted repository root or OS temporary
root, then reject symlinks and Windows reparse points in every component below it.
POSIX `/tmp` and `/var/tmp` are also trusted temporary anchors, so macOS system
aliases do not invalidate the documented report examples. Descendant links are
not resolved away; even links back into the same root are rejected. Parent
traversal is rejected. Report outputs may be absent, but existing ancestors are
still checked. These checks do not remove same-user filesystem race risks.

Linux fixtures simulate aliased roots and Windows reparse metadata. Native
macOS/Windows validation is still a required pilot step, not implied by passing
these simulations.

## GitHub repair inputs (L2)

Run and jobs responses must be objects; repository objects, names, positive
integer IDs/attempts, job arrays and step arrays are validated before access.
Null/scalar/array responses, boolean IDs, malformed nested fields and invalid
UTF-8 JSON produce controlled validation errors before repair allocation.
Refetched runs undergo the same validation. Existing repository/workflow/event,
exact-head and attempt/rerun checks still apply.

## Additional audit disposition

- **L5:** Strict routing accepts legacy dated IDs such as
  `claude-3-5-sonnet-20241022` as well as newer pinned naming. Aliases remain
  rejected. Syntax acceptance does not establish model availability in an account.
- **L6:** Attempt limits are an operator honesty guardrail. Identical-scope
  replacement tickets must declare `supersedes`, and declared replacements inherit
  attempts. An operator changing scope can submit new work. This is intentionally
  not adversarial identity or budget enforcement.
- **L7:** Credential refresh write-back still has a compare/replace race with
  another CLI refreshing the same login. It is not a cross-process compare-and-swap.
  Use dedicated isolated runtime identities before moving beyond the local pilot.
- **L8:** `factory.update` rejects columns outside a fixed internal allowlist
  before accessing SQLite; values remain parameterized.
- **L9:** Keep the native XML byte cap and DTD/entity rejection. The current audit
  did not establish a reason to replace this stdlib parser.
- **L10:** The dashboard displays the current configured total attempt limit
  (two when `max_repairs` is one), or `?` when config is unavailable. Unused imports
  and assignments touched by this pass were removed. Base-ref syntax validation
  and SQLite WAL tuning remain follow-ups; transient reader errors remain visible
  and polling retries without inventing new ledger state.

## Gate before use beyond a local pilot

All acceptance requirements in AUDIT.md remain binding. In particular:

1. Isolate builder, tests, verifier and controller identities and filesystems;
   restrict secrets, network, processes and resource usage, and test teardown.
2. Operate a trusted verification/signing service with externally pinned policy,
   harness and images. Bind signed receipts to repository, candidate/base/merge-group
   SHA, specification, policy/toolchain digests, results and expiry.
3. Enforce GitHub branch protection/rulesets with the trusted verifier App's
   checks, no unauthorized bypass or force-push, and a merge queue testing the
   combined candidate against the current base.

Project-specific full-stack tests, release/rollback contracts and the operational
pilot in AUDIT.md are also required. Local READY, unsigned receipts, local human
attestations and draft PR status cannot substitute for these controls. This pass
does not configure external identities, a signing service or GitHub rulesets.
