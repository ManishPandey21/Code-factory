> Historical v0.3.x validation. For current results see [VALIDATION_V041.md](VALIDATION_V041.md).

# Validation evidence

## v0.3.1 (audit fixes)

Run on Linux, Python 3.13.18, Git 2.43.0, with ResourceWarning promoted to an error:

```text
python -W error::ResourceWarning -m unittest discover -s tests
Ran 102 tests in 145.261s
OK
```

That is the 81 original tests plus 21 regressions in `tests/test_regressions_v031.py`. The unmodified 0.3 package was first confirmed at 81 passing, and each defect in CHANGELOG.md was reproduced against it before the fix. The evidence boundaries below are unchanged: fake agents, fake `gh`, a local bare remote, no Windows/macOS run, no live Claude/Codex or GitHub. The Windows liveness probe in particular is untested code.

# v0.3 validation evidence

10 November 2026. Final frozen-code run:

```text
python -m unittest discover -s tests -v
Ran 81 tests in 61.930s
OK
```

`python -m py_compile factory.py agent_bridge.py configure.py cold_workspace.py verification_policy.py test_report.py` and `git diff --check` also passed. Full test output: VALIDATION_LOG.txt.

An independent reviewer read the source/diff, reproduced an optimized-Python status defect, and reported missing spec fields in the bundled examples. Both were fixed. The reviewer then independently ran the optimized-status, example-validation and external-tool-mutation regressions: 3 passed in 4.536s. Independently reviewed factory.py SHA256: `69ce49ff713fadbe6bb27ef1792645c12dd563baf5076d89baa82c2ffd71e00d`.

## Coverage

- Real Git repositories, two overlapping builder subprocesses, distinct candidates, four independent review invocations, dependency/overlap dispatch and stale-base rejection.
- Original false-READY reproduction: an ignored builder-only artifact cannot satisfy cold checks.
- Exact detached independent repositories, no source hooks/config/remotes/shared object inode; absent builder ignored files; ancestry and timeout rejection.
- Frontend-only, backend-only, shared/unknown and both-stack policy selection; both-stack requires contract checks; missing suite kinds/spec sections cannot pass.
- Native JUnit subprocess adapter: successful real testcase entries, nonzero exit, timeout, failures/errors/skips, empty/missing/stale/unsafe XML, counts mismatch, symlink and traversal rejection.
- Review lacks evidence/file/acceptance attestation, stale SHA, mutation or rejection -> BLOCKED.
- Changed external executable/script, config, candidate or evidence blocks publication. Executed publication failure revokes eligibility.
- Ephemeral reviewer homes, no inherited settings/history/plugins/session environment, limited provider credentials, stale result/prompt mutation and failed CLI envelopes.
- Publication/reuse via fake gh plus real local bare Git remote; remote-base mismatch, no duplicate draft, exact candidate checks.
- Bounded retries, lock rejection, retained failed work, non-destructive rejection, refusal to reject an already merged candidate, optimized-Python status correctness.

## Evidence boundaries

The models, GitHub service and test category reports in coordinator tests are fixtures. Those tests prove the controller accepts/rejects specific evidence and executes independent processes, not that an AI found every bug or that a visual suite renders real pixels. Native JUnit parsing is tested with subprocess-produced native fixture XML. No production application, actual browser suite, live Claude/Codex authentication, real GitHub rulesets/CI/merge queue, Windows/macOS runtime or deployment rollback was exercised.

Linux local validation is green. Production readiness is **NOT VERIFIED**. See AUDIT.md for the remaining high-severity architectural/deployment blockers. No numeric readiness score is assigned without that evidence.
