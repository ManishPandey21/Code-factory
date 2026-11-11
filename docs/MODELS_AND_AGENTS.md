# Models, agents, effort and resource bounds

Version 0.4.0 removes automatic model assignments. Choose an available full model
ID with `configure.py --provider PROVIDER --model MODEL --effort medium`, then
use `--route ROLE=PROVIDER:MODEL:EFFORT` for any specialized role. Configuring one
provider fills all seven worker/reviewer roles; it does not require both CLIs.
No model availability or quality claim follows from a model string.

## Roles

- Coordinator: the active Claude or Codex session; owns requirements and allocation.
- `builder_routine`, `builder_complex`, `builder_critical`: implement scoped tickets.
- `reviewer_standards`, `reviewer_spec`: fresh code reviewers.
- `reviewer_standards_critical`, `reviewer_spec_critical`: critical-ticket overrides.

EGM design reviewers run through the official EGM plugin before these code
workers. See [EGM_WORKFLOW.md](EGM_WORKFLOW.md) for both host workflows.

Routing is by **risk and complexity**, not by frontend/backend: which suites run is decided by the
ticket's `paths` (verification policy), which builder runs is decided by `role: critical` and
`complexity`. Configurations without `builder_*` keys keep routing by `role` (pre-0.3.4 behaviour).
Use role overrides for measured, project-specific escalation policies.

Codex stays a supported provider for any role: `configure.py --route builder_routine=codex:MODEL:medium`.
Codex accepts `low`, `medium`, `high` (passed as `-c model_reasoning_effort=...`). Codex reports
no per-run model usage to the bridge, so its evidence records `served_models_verified: false`.

## Routing controls and validation limits

The following Claude CLI observations were reported by the input v0.3.4 archive.
They were not independently verified against a live Claude installation in this
audit. Fake-CLI tests exercise the adapter logic; test your installed CLI before use.

| Risk found | Behaviour of the CLI | What the bridge does |
|---|---|---|
| Effort typo | `--effort ultra` is accepted silently (exit 0) | Effort must be one of `low medium high xhigh max` (`low medium high` for Codex); anything else is refused before the CLI starts |
| Environment overrides the flag | `CLAUDE_CODE_EFFORT_LEVEL` "overrides effort for this session", even over `--effort` | Sets `CLAUDE_CODE_EFFORT_LEVEL` to the requested effort **and** passes `--effort`, so both agree |
| Settings cap clamps silently | `maxEffortLevel` in any settings file (lowest wins) clamps `--effort` without reporting it | Reads managed, user and project settings; a cap below the request refuses the run |
| Alias remapping | `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL`, `ANTHROPIC_MODEL` can change what an alias means | Requires full model ids (a provider-issued full ID, not `opus`) and removes those variables for the run |
| Silent fallback | `--fallback-model` / overload fallback can switch models | Never passes `--fallback-model`; sets `CLAUDE_CODE_NO_MODEL_FALLBACK=1`; refuses the result unless `modelUsage` shows the requested model served the run |
| Unknown or unavailable model | `is_error: true`, exit 1 | The run fails closed (the ticket blocks); evidence records `cli_failed` |

Not observable: the CLI does not report the *effective* effort of a run (not in the result
envelope, the init message or the debug log). The bridge therefore controls every input it can
(flag, environment, caps) and records them; it cannot prove what the server applied. An
organisation-level per-model effort cap set on the account is invisible locally.

## Evidence per agent run

Next to each result file the bridge writes `<result>.routing.json` (mode 0600, exclusive create,
stale files refused): provider, mode, requested model and effort, the effort controls applied, the
overrides removed, settings caps found, models that served the run with token counts and cost,
duration, turns, the names of tools whose use was denied (never their inputs), exit status and an
outcome (`ok`, `cli_failed`, `routing_refused`, `error`). It never contains credentials or
environment values. Builders also keep their full `stream-json` transcript
(`builder-result.transcript.jsonl`). The factory records the builder's routing in the ledger and
attaches each reviewer's to its review; for a strict command, missing or unsuccessful routing
evidence blocks the ticket. Schema, exit status, provider, requested model and
effort must match the configured route. The controller preserves the explicit
`served_models_verified` flag; Codex remains unverified for served-model identity.

## Evaluating the routing

After every completed ticket, keep per role/model/effort: outcome (READY first time, attempts used,
BLOCKED reason), review findings by severity, cold-suite failures caught after the builder, tokens
and cost from the routing evidence, and wall-clock time. Change a default only when a few tickets
of the same complexity show a consistent difference (for example routine tickets that keep
blocking on Sonnet/medium, or complex tickets that pass first time on Sonnet). Record the change and
its evidence in the project's decision log.

## Resource bounds

Use one durable coordinator, up to two builders, and fresh reviewer processes. A process semaphore
caps active CLI subprocesses at two. Workers and reviewers do not allocate further agents.
`timeout_seconds` bounds each process, not total project cost.

## Sources

- Claude Code model configuration and aliases: https://code.claude.com/docs/en/model-config
- Claude Code headless use: https://code.claude.com/docs/en/headless
- Local `claude --help` (2.1.322): `--effort <level>` (low, medium, high, xhigh, max), `--fallback-model`.
- Codex non-interactive runs: https://developers.openai.com/blog/codex-as-a-platform
