# 0.4.0 — EGM integration candidate

- Add official EGM workflow instructions and matching Claude/Codex skill entries.
- Add `egm.py` to bind approved designs, five review-stage reports and ticket scope.
- Add opt-in `workflow: egm` enforcement at intake, execution, status and publication.
- Require explicit provider/model configuration; all roles can use either provider.
  **Migration:** previous configure invocations without a complete set of routes
  now require `--provider` and `--model`. Existing generated configs still load.
- Validate strict routing receipts against configured provider/model/effort and
  preserve served-model verification limits in controller evidence.
- Add regression and real-Git handoff tests. No paid model run, GitHub publication,
  merge, deployment or external plugin installation performed in this audit.

# Changelog

## 0.3.4 — model/effort routing and attempt history (11 November 2026)

### Added

- **Strict routing** (`agent_bridge.py --strict-routing --effort LEVEL`): pinned full model ids, explicit
  effort passed as both `--effort` and `CLAUDE_CODE_EFFORT_LEVEL` (the CLI lets the variable override the
  flag), model-remapping variables removed, no model fallback, settings `maxEffortLevel` caps refused
  instead of silently clamped, and the result refused unless the requested model served the run.
  The Claude CLI accepts unknown effort names silently, so effort is validated here.
- **Routing evidence**: `<result>.routing.json` per agent run (requested vs. served model, effort controls,
  tokens, cost, duration, denied tool names, outcome; never credentials) and the builder's full
  transcript. The factory records it in the ledger / review and blocks when a strict command produced none.
- **Risk/complexity routing**: optional ticket field `complexity` (`routine` | `complex`); commands
  `builder_routine`, `builder_complex`, `builder_critical`, and `reviewer_<lens>_critical` escalation for
  `role: critical`. Older configurations keep routing by `role`.
- **Attempt history across replacement tickets**: optional ticket field `supersedes`. A replacement
  inherits the highest attempt count of what it replaces and closes it (REJECTED, history kept); a ticket
  with the same paths as an unfinished ticket that has used attempts is refused unless it declares
  `supersedes`; an exhausted history cannot be renamed into a new budget.
- `configure.py` writes pinned, effort-explicit, strict commands for every role (`--route` overrides).

### Release manifest

The 0.3.3 archive shipped the 0.3.1 `SHA256SUMS`: the four entries that did not match
(`CHANGELOG.md`, `README.md`, `factory.py`, `tests/test_regressions_v031.py`) are exactly the files 0.3.2
and 0.3.3 changed, and every 0.3.1-era file matched. This release regenerates the manifest from the
reviewed 0.3.4 tree. A manifest shipped beside the code still proves nothing against a modified copy:
pin the runtime hashes in the consuming project.

## 0.3.3 — audit fixes (11 November 2026)

### Fixed

- **Reviewers were not shown the source of a rename.** Cold evidence `files` and the saved diff used default rename detection, which omits the deleted path. Both now use `--no-renames`, so a PASS must attest every added, modified and deleted path.
- **A merged blocked candidate never unblocked dependents.** Ancestry promotion only looked at READY. A BLOCKED head that was merged anyway left dependents PENDING forever. Merged BLOCKED heads become MERGED. An unmerged BLOCKED ticket is not rewritten to READY.
- **Parallel worktree creation and commits.** `worktree add` and the controller commit take a shared lock. Two tickets still build and review concurrently; only the shared Git mutations are serialized.
- **Control characters in ticket paths** are rejected so a newline cannot desynchronize the porcelain parser.

### Not changed

Same-account execution is not a sandbox. There is still no automatic merge or production revert. The full-stack minimum matrix is unchanged.

## 0.3.2 — audit fixes (11 November 2026)

Reproduced on the unmodified 0.3.1 tree before the change. Linux only; not exercised on Windows, macOS, real Claude/Codex CLIs, or GitHub.

### Fixed

- **Out-of-scope deletion hidden as a rename.** After the controller commit, scope was checked with `git diff --name-only`. Rename detection lists only the destination, so a commit that deletes a file outside the ticket by renaming it onto an allowed path looked in-scope and could reach READY. Scope now uses `--name-status --no-renames`. The controller commit also runs with an empty `core.hooksPath` and `--no-verify`, so a repository `pre-commit` hook cannot restage extra paths into the candidate.
- **Dependency cycles waited forever.** A ticket whose dependency chain returned to itself stayed PENDING with "dependencies not merged". `add` now rejects the cycle.
- **Intake was invisible in the ledger.** `add` wrote no event row. It now records PENDING.

### Not changed

The trust model is unchanged: same-account execution is not a sandbox, merge and production revert stay manual, and the minimum full-stack test matrix (frontend unit/component/visual/e2e, backend unit/api/integration, shared contract) is unchanged. See `docs/AUDIT.md`.

## 0.3.1 — audit fixes (10 November 2026)

Every item below was reproduced against the unmodified 0.3 package before it was changed, and each has a regression test in `tests/test_regressions_v031.py`. Linux only; nothing here was exercised on Windows or macOS, with real Claude/Codex CLIs, or against GitHub.

### Fixed

- **Overlapping candidates from one base.** A PENDING ticket whose paths overlap a READY-but-unmerged (or in-flight) ticket was dispatched anyway. Unmerged candidates now hold their paths until merged or rejected.
- **Publication destroyed verification on transport noise.** stderr was merged into parsed stdout, so an SSH host-key warning on `git ls-remote` produced a false "origin base differs", and a `gh` update notice broke PR lookup after the branch was already pushed. Both revoked READY. stderr is now kept in `<log>.stderr`.
- **Network/auth/CLI failures revoked READY.** A missing remote, an offline network or an absent `gh` forced a full rebuild and consumed one of three attempts. Transport failures now leave READY intact with an explanatory `error`; rerunning `publish` resumes. Identity, evidence and remote-base mismatches still revoke.
- **Unrecoverable lock.** A controller killed outside a ticket run left `coordinator.lock` with no command able to clear it. New `unlock --repo PATH` removes it only when the owner is a dead process on this host and no ticket is in flight.
- **Terminated controller orphaned its agents.** SIGTERM left builders/reviewers running, the lock held and the ticket RUNNING. SIGINT/SIGTERM now kill owned process groups, release the lock and record BLOCKED. Ctrl-C previously waited for agents to finish.
- **Windows: liveness probe killed the probed process.** `os.kill(pid, 0)` calls `TerminateProcess` on Windows. Replaced with a query. *Written from the documented API; not executed on Windows.*
- **Reviewer profile could sign the owner out.** The bridge copied the rotating OAuth credential file into a temporary profile and deleted it. A token refreshed there was lost while the original kept a spent refresh token. A refreshed credential is now written back atomically, unless the original changed concurrently (then nothing is overwritten and a warning is printed).
- **Reviewer profile dropped proxy/CA settings.** `HTTPS_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS` and related variables now pass through.
- **Guard missed common manifests.** Edits to `package-lock.json`, `pnpm-lock.yaml`, `go.mod`/`go.sum`, `tsconfig*.json`, `setup.py`, `Cargo.toml` and similar were accepted; `*_test.*`, `e2e/` and `cypress/` tests were not recognised. The list is wider but remains a heuristic: add project-specific files to `protected_paths`.
- **Late symlink/submodule refusal.** A repository containing any symlink blocked every ticket only after the builder had run and an attempt was spent. Now refused at `run`, before dispatch.
- **Audit trail gaps.** `retry`, `recover` and merge detection changed state without an event row.
- **One invalid queued ticket aborted every run.** Such tickets are now skipped and reported.
- **Smaller:** `run` output explains every waiting ticket; builders are told up front which edits cause rejection; a mixed PASS/INCONCLUSIVE review is no longer labelled CHANGES_REQUIRED; ledger connections are closed; malformed `commands`/`checks`/`protected_paths` give a clear error.

### Behaviour changes to be aware of

- `run` prints a `waiting` object next to `selected`.
- A failed `publish --execute` no longer always ends in BLOCKED; check the ticket's `error` field.
- An interrupted run marks in-flight tickets BLOCKED and counts as an attempt.

### Not changed

The trust model, the hard-coded minimum test matrix, zero-skip rule, state directory location and CLI permission flags are unchanged. See the audit report for the open findings on each.
