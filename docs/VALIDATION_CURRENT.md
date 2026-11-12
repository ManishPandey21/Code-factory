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
tests currently discovered. Counts for targeted reruns are not additive.
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

## Limits

Only Linux was executed locally. GitHub Actions now runs the complete suite on
Linux, macOS and Windows with Python 3.10 and 3.14, but those hosted jobs were not
run from this workspace. POSIX-only fixtures explicitly skip on Windows.

Workers/reviewers and GitHub responses are deterministic fixtures. No live model,
authentication or GitHub publication was exercised. The mutation probe runs real
unittest assertions; it does not prove complete application coverage or semantic
quality of future operator-selected mutations. Tracing remains best-effort local
metadata and is never verification evidence or authorization.
