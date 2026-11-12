# Named evidence and controlled failures

Every selected verification check must now demonstrate both passing behavior and
sensitivity to a deliberate defect. This is a breaking evidence/policy change:
old count-only reports and old READY receipts require fresh verification.

## Configure a negative control

Each check keeps its existing fields and adds `negative_control`:

```json
{
  "id": "backend-api",
  "domains": ["backend"],
  "kind": "api",
  "argv": ["python", "/tools/test_report.py", "--report", "{report}",
           "--junit", ".test-output/api.xml", "--mode", "{test_mode}",
           "--", "python", "-m", "pytest", "--junitxml=.test-output/api.xml"],
  "report": "api.json",
  "min_tests": 1,
  "negative_control": {
    "argv": ["python", "/trusted-ci/disable_password_validation.py", "{worktree}"],
    "expected_failures": ["[\"pytest\",\"tests.test_login\",\"test_rejects_bad_password\"]"]
  }
}
```

Replace the mutation and test ID with project-specific values. The policy and
mutation scripts are trusted operator inputs, reviewed separately from tickets.
Choose a defect that challenges the behavior the suite is supposed to protect,
e.g. bypass a validation condition. Mutation scripts must modify production
files in the supplied checkout and exit successfully. They may not change HEAD,
tests, instructions, manifests, runner configuration or configured protected paths.
A no-op mutation blocks the ticket. Use absolute paths for trusted scripts so the
controller pins their bytes along with the test runner. Do not change tests to
manufacture a failure.

The controller runs the check normally, creates a separate fresh candidate clone,
reruns preflight setup, applies the mutation, then runs the same check command with
`{test_mode}` set to `fail` instead of `pass`. The native command must exit nonzero
and produce a JUnit assertion failure for exactly the declared test IDs. The
adapter accepts known AssertionError/AssertionFailedError types and native pytest
assertion-message prefixes. Unknown failure types (including runtime exceptions
encoded as `<failure>`) fail closed; other runners need a trusted adapter that
classifies assertion failures explicitly. A timeout,
missing report, collection/runtime error, skipped test, changed inventory or
surviving mutation blocks readiness before a reviewer can approve it. A failed
mutation command is an infrastructure failure, not test sensitivity evidence.

Native XML paths must be fresh and ignored by Git (configure this in the reviewed
base); normalized JSON reports are written outside the checkout. Tests must not
modify tracked files. The mutated clone and evidence are retained for inspection;
no automatic cleanup or reset touches the original candidate. Each review lens
runs its own controls. Expect additional test runtime and disk use.

## Named reports and acceptance references

Normalized reports have `status`, `total`, `passed`, `failed`, `skipped`, and a
`tests` array of `{id, status}` objects. IDs are compact JSON arrays containing
ancestor testsuite names, classname (empty if absent), and test name. Use the exact
ID emitted by the adapter; parameterized names remain distinct. Missing names and
duplicate identities fail closed. Counts must match the enumerated tests.

A PASS review retains `acceptance_covered` and adds `acceptance_tests`:

```json
{"acceptance_tests": [
  {"acceptance": 0, "tests": [
    {"check": "backend-api", "test": "[\"pytest\",\"tests.test_login\",\"test_rejects_bad_password\"]"}
  ]}
]}
```

There must be one mapping for every zero-based criterion in the manifest's
`acceptance` list: ticket acceptance first, then ui, api, data, cross_cutting.
Every reference must identify an observed passing test in the named check.
Duplicate, unknown, empty and missing mappings are rejected. Reviewers still
assess whether the cited test actually supports the criterion; identity matching
cannot establish semantic coverage by itself.

Manifests use version 2 and retain hashes of passing and negative reports, logs,
mutation diffs and trusted tools, bound to the exact candidate/base/config/ticket.
Publication rechecks hashes, test mappings and negative-control identities.
Count-only legacy policies cannot silently opt out: update configuration, commit
it through the policy-maintenance workflow, and run fresh verification.

This remains trusted local orchestration, not a malicious-worker sandbox or a
proof of complete test quality. A poorly chosen mutation can establish sensitivity
to the wrong behavior; review the mutation and criterion-to-test mappings.

## Module boundaries

- `factory.py`: CLI parsing, command handling, guarded draft publication; legacy
  imports are re-exported for existing callers.
- `records.py`: ticket validation and transactional SQLite records.
- `dispatch.py`: route selection, scheduling, builder/reviewer orchestration.
- `evidence.py`: cold checks, negative controls, evidence and publication validation.
- `instructions.py`: builder/reviewer/risk prompt construction without execution.
- `runtime.py`: configuration, shared process controls and Git/path boundaries.

The dependency direction is CLI → dispatch → records/evidence → runtime.
Instruction construction depends only on JSON, paths and skill prompt helpers.
Tests should patch the owning module, e.g. `records.record`, not the CLI re-export.

## Automated validation

`.github/workflows/tests.yml` runs the full unittest suite and compilation on
Linux, macOS and Windows with Python 3.10 and 3.14 for pushes and pull requests.
POSIX-only executable/signal fixtures keep explicit skips on Windows; portable
orchestration, reports, policy and configuration tests still run there. CI results
must pass before claiming a particular platform is validated. No paid providers
or GitHub publication are invoked by the suite.
