# Skill routing by workflow

For `workflow: egm`, use the official EGM plugin for requirements/design:
`egm-brainstorm` → `egm-draft` → `egm-review` → `egm-resolve`, then actual human
approval and `egm.py` handoff. Use `egm-drift-report` after implementation.
See [EGM_WORKFLOW.md](EGM_WORKFLOW.md). Do not also run grill-me/to-spec for the
same design. Ticket decomposition, TDD, debugging, cold code review and final
verification remain shared implementation stages.

## Classic workflow: seven primary skills

The planning assignments and invocation instructions below apply to the classic
workflow. The external skill installation advice is relevant only for skills
chosen by the active workflow.

Exactly one **primary** skill is selected at each stage. Some upstream skills require helpers; their requirements cannot honestly be described as zero additional skill use. Do not load the full catalogue, run competing orchestrators, or replace a skill's required checks with a passing label.

| Job | Primary skill | Provider | Owner |
|---|---|---|---|
| Resolve requirements | grill-me | Matt Pocock curated collection | Coordinator, with owner |
| Formalize agreed design | to-spec | Matt Pocock curated collection | Coordinator |
| Create vertical tickets | to-tickets | Matt Pocock curated collection | Coordinator |
| Implement a behavioral ticket | test-driven-development | Superpowers | Assigned builder |
| Diagnose a failure | systematic-debugging | Superpowers | Assigned builder, only after failure |
| Review candidate | code-review | Matt Pocock curated collection | Coordinator dispatches fresh spec and standards leaf reviewers |
| Confirm completion | verification-before-completion | Superpowers | Coordinator, using actual check/review receipts |

Coordinator tracking is implemented by the factory ledger; it does not need master, masterofall, dream, wayfinder or another orchestration skill. No change is made to those existing skills. Context continuity is the ledger, task specification, Git state and bounded logs.

## Upstream dependencies and conflict handling

Matt code-review requires independent standards and specification reviewers. The coordinator launches those leaves from raw requirements and the candidate; a builder never reviews its own implementation. Leaves receive their lens rather than instructions to recursively run code-review. Superpowers debugging refers to TDD and verification; the coordinator transitions between the predefined stages rather than growing an unrestricted tree of agents.

Do not run Superpowers brainstorming and Matt grill-me for the same requirement phase. Do not run Superpowers writing-plans and Matt to-tickets as competing ticket generators. Do not combine subagent-driven-development with a second active allocator. Existing global plugins can still auto-trigger; inspect applicable instructions and resolve conflicts during onboarding. The runner does not silently disable installed plugins.

## Installation and discovery

Matt's selected skills were available in this ChatGPT environment; that does not establish that they exist on either local desktop. The public upstream is https://github.com/mattpocock/skills ; the installed curated package is a separate distribution and is not assumed byte-identical to upstream. In the target coding workspace, locate each selected skill by its actual SKILL.md name/frontmatter and read its requirements. Configure the actual local paths. If absent, report the missing capability and install it through the owner's existing supported skill/plugin workflow; do not fetch an unrelated similarly named package.

Superpowers upstream: https://github.com/obra/superpowers . Follow its instructions for the selected Claude Code/Codex host and inspect the pinned revision. Prefer keeping the selected skill's full directory, including referenced resources, accessible; copying only SKILL.md can break dependencies. No third-party skill source is bundled with this toolkit.

A skills inventory should record provider, name, local path, version/hash, helper dependencies, primary job and availability. Avoid reading credential stores or printing environment variables. During each worker launch, use only the mapped primary skill and required helpers. Missing required skills are a setup blocker, not a reason to claim the workflow ran.

Scope Superpowers TDD's instruction about removing pre-test implementation to the worker's own new uncommitted code. Never delete pre-existing or unrelated user code. Read required references such as writing-good-tests.md when changing tests. A failed import, unavailable service or timeout does not prove the behavior test detects the intended regression.


## Verified upstream installation options

The author's name is Matt **Pocock**. Current upstream README: https://github.com/mattpocock/skills . Choose one install mechanism per host to avoid duplicate skills.

Claude Code terminal:

```bash
claude plugin install mattpocock-skills@claude-plugins-official
```

Codex terminal (check your installed CLI supports the plugin subcommands):

```bash
codex plugin marketplace add mattpocock/skills
codex plugin add mattpocock-skills@mattpocock
```

Run `/setup-matt-pocock-skills` once per repository. The upstream distinguishes user-invoked planning skills from model-invoked skills. When that installed version requires an explicit invocation, the owner invokes `/grill-me`, `/to-spec`, and `/to-tickets` at those stages; the factory must not bypass its invocation policy. For ongoing repository domain-model/ADR interviews, upstream recommends `grill-with-docs`; adopting it replaces the interview entry rather than adding a second interview workflow. This package's initial interview profile remains `grill-me` as requested.

Superpowers: https://github.com/obra/superpowers . Current README offers `/plugin install superpowers@claude-plugins-official` inside Claude Code, and Plugins → Coding → Superpowers in Codex App (or `/plugins` in Codex CLI). Verify the local version's instructions before installation. No installer was executed on the owner's computer.
