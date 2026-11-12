# Current hardening validation

13 November 2026. Local environment: Linux, Python 3.12.14, Git 2.52.0.

| Check | Result |
| --- | --- |
| Original baseline at `4e46acb15422e0f4bd6e69c93883def9c190f575`, isolated snapshot | 181 passed |
| Main regression discovery | 206 passed in 951.489 seconds |
| Added usage-tracing suite, with ResourceWarning treated as error | 8 passed in 2.409 seconds |
| SQLite fixture cleanup subset, with ResourceWarning treated as error | 8 passed in 4.648 seconds; overlaps suites above |
| Compile all Python sources | Passed |
| `git diff --check` | Passed |
| Example verification policy | All 8 required checks validate with negative controls |
| CI workflow YAML and matrix | Parses; 3 operating systems × 2 Python versions |

The main regression run and subsequently added tracing suite cover all **214**
tests discovered before integrating the newer main branch. Counts for targeted reruns are not additive.
Full outputs: [regression log](VALIDATION_CURRENT.log) and
[tracing log](VALIDATION_USAGE.log).

Reproduce the complete suite with:

```sh
python -m unittest discover -s tests -v
python -m compileall -q .
git diff --check
```

The initial named-evidence regressions were also observed failing before the
implementation: count-only evidence, unnamed/duplicate tests and unsupported
acceptance references were accepted by the old implementation.

## Integration with main

Integrated `a780fce` while retaining its runtime-version checks, path safety,
protected command inputs, ticket-update whitelist and UTF-8 handling. All 234
combined tests passed with ResourceWarning treated as an error (four isolated
module runners, 443.449 seconds). Three additional interaction regressions passed,
for **237 unique tests** in the final suite. Compilation and diff checks passed.
Full output: [integration log](VALIDATION_MERGE.log).

The interaction tests ensure negative-control destinations remain editable while
configured check runners and mutator scripts remain protected. Independent
reviews found no remaining blocking issues after these fixes.

## Verified behavior

- Native named test identities survive normalization; counts alone cannot pass.
- A real unittest assertion passes for the candidate, fails after an isolated
  production mutation, and leaves the original candidate unchanged.
- Surviving/no-op mutations, runtime errors, unknown failure classifications,
  changed inventories, wrong failing IDs, test/config mutations and tampered
  artifacts block readiness/publication.
- Acceptance mappings reject missing, duplicate, non-passing or invented references.
- Suffix-colliding check IDs retain distinct artifacts.
- Versioned holds survive commands, stale releases fail, and event failures roll
  back hold/release state atomically; held work cannot bypass existing gates.
- GitHub intake validates source identity, previews without durable ticket writes,
  replays without resetting work, preserves source snapshots, rejects duplicates,
  and rolls back ticket/link changes together. Draft bodies reference the issue;
  linked `gh` operations pin their repository and validate returned PR URLs.
- Canonical skill TOC labels, order and anchors match headings. Both host wrappers
  and relative documentation links resolve correctly.
- Local tracing records start/finish metadata across concurrent processes and
  retains unmatched starts after a hard exit. Private arguments/content are not
  recorded. Corrupt/unavailable tracing preserves results, holds and stdout.
- Independent standards/spec reviews found issues in CI context placement,
  assertion classification, artifact naming and PR repository selection. All were
  corrected; the subsequent tracing review found no actionable defects.

## Hosted portability follow-up

The initial hosted run passed both Linux and macOS Python versions. Windows
Python 3.10 identified one fixture assertion that assumed `/` separators. It now
compares `Path.parts`, preserving the expected directory and filename on each
platform. The eight-test skill-inventory suite passes after the correction;
these tests overlap the 237-test total. The final hosted matrix is required
before merging.

## Limits

Only Linux was executed locally. GitHub Actions now runs the complete suite on
Linux, macOS and Windows with Python 3.10 and 3.14, but those hosted jobs were not
run from this workspace. POSIX-only fixtures explicitly skip on Windows.

Workers/reviewers and GitHub responses are deterministic fixtures. No live model,
authentication or GitHub publication was exercised. The mutation probe runs real
unittest assertions; it does not prove complete application coverage or semantic
quality of future operator-selected mutations. Tracing remains best-effort local
metadata and is never verification evidence or authorization.
