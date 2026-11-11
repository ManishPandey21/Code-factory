# Machinist review and Code Factory adaptations

Reviewed [owainlewis/machinist](https://github.com/owainlewis/machinist/tree/4d7d77664b5dcf93b6d0b034f7dfac02e42e11c8)
at commit `4d7d77664b5dcf93b6d0b034f7dfac02e42e11c8` on 11 November 2026.
This was source/document review; Machinist was not installed, built or run.
Repository text was treated as reference material, not instructions for this task.

Machinist is a Go control plane with a React interface and native Claude/Codex
workers. It supports local, remote VM and Kubernetes execution, a standard staged
pipeline, single-agent jobs, automation, and GitHub follow-ups. Code Factory is a
smaller local Python controller with EGM design handoffs, cold checks and two
independent code-review lenses. The useful overlap is durable operational state
and native CLI coordination; copying the entire control plane is unnecessary for
this change.

| Machinist mechanism | Source evidence | Code Factory decision |
|---|---|---|
| Durable private publication holds; current-version release | [Local jobs](https://github.com/owainlewis/machinist/blob/4d7d77664b5dcf93b6d0b034f7dfac02e42e11c8/docs/local-factory/local-jobs.md#recovery-and-privacy), `internal/controlplane/github_factory_server.go`, `TestPrivateHoldSurvivesRestartAndAllNormalActions` | Implemented private per-ticket holds, increasing versions, explicit release, audit events and dispatch/retry/publication guards. Inactive held tickets also reserve paths and cannot be superseded. |
| Duplicate-safe submission with a stable request identity | [Local jobs API contract](https://github.com/owainlewis/machinist/blob/4d7d77664b5dcf93b6d0b034f7dfac02e42e11c8/docs/local-factory/local-jobs.md#two-built-in-modes) | Implemented opt-in `add --idempotent`, using the existing ticket ID and validated content as identity; mismatched replays fail. No separate HTTP request-key system is needed for this CLI. |
| Private state and logs separate from published delivery | README and local jobs recovery guidance | Retained the Git-common-directory runtime; hold reasons/events stay local. Documented complete-runtime backup and old-binary limitations. |
| Recovery state visible after restarts | Local jobs recovery guidance | Status now reports holds even with invalid config, with an explicit configuration error and no current-verification claim. Execution still rejects that config. |
| Same-PR repairs triggered by CI/review feedback | `docs/local-factory/github-followups.md` | Deferred: requires trusted feedback provenance, remote permissions, PR identity checks and a new lifecycle design. Existing bounded manual retry remains. |
| Separate execution identities and gVisor jobs | `docs/local-factory/kubernetes.md` | Recommended future hardening; this change does not claim sandbox isolation or require Kubernetes. |
| Scheduled maintenance and narrow auto-merge | `docs/local-factory/automations.md` | Not adopted: Code Factory continues explicit execution and draft publication, with no automatic merge/deploy. |
| Native single-agent mode with advisory child review | README / `docs/native-agents.md` | Not adopted: retain enforced EGM handoff and cold independent verification for the selected workflow. |

The hold/replay implementation is a local adaptation written for Code Factory's
ledger and locking model, not a vendored Machinist component or an assertion of
behavioral equivalence. Machinist's public source is MIT-licensed; see its LICENSE.

## Verification and remaining limits

New tests run actual factory CLI commands and real Git repositories. They verify
cross-command hold persistence, stale releases, state/attempt/event preservation,
overlap protection, blocked replacement/retry/publication, identical and changed
replays, broken-configuration status, and external-merge reconciliation. Worker
processes are deterministic fixtures. No remote publication, authenticated provider
pilot or Machinist runtime test is claimed. See [VALIDATION_V042.md](VALIDATION_V042.md).

These controls are not an authenticated approval service or an OS boundary. A
hold cannot cancel an external write already issued, and old binaries cannot be
trusted to honor a control they do not implement. The [usage guide](TICKET_CONTROLS.md)
spells out these limits and upgrade behavior.
