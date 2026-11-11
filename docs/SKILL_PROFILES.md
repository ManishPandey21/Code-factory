# Matt Pocock + Superpowers profiles for Claude and Codex

Use the complete upstream distributions, including their referenced resources.
This toolkit integrates their installed files; it does not vendor modified copies
or claim that a configured skill was executed by a model. Both hosts use the
same inventory and conditional builder instructions.

Sources inspected on 11 November 2026:

- [Matt Pocock](https://github.com/mattpocock/skills/tree/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d)
- [Superpowers](https://github.com/obra/superpowers/tree/22f0b463e7a5e579904dd6211a520321035526f7)

## Select by task

| Need | Skill | Owner / trigger |
|---|---|---|
| Tracker, glossary and ADR conventions | Matt `setup-matt-pocock-skills` | Explicit user invocation, once per project |
| Resolve terminology and architectural choices | Matt `domain-modeling` | Coordinator, when terms/ADRs change |
| Explore uncertain UX/behavior cheaply | Matt `prototype` | Coordinator, only for a specific unresolved question |
| Verify API/library facts | Matt `research` | Coordinator, when evidence is missing |
| Convert approved EGM design into vertical tickets | Matt `to-tickets` | Explicit user invocation; map results to factory JSON |
| Improve module boundaries | Matt `codebase-design` | Builder only when the ticket changes boundaries |
| Implement behavior with regression tests | Superpowers `test-driven-development` | Builder primary skill |
| Diagnose failed tests or runtime surprises | Superpowers `systematic-debugging` | Builder only after failure |
| Evaluate feedback before applying fixes | Superpowers `receiving-code-review` | Builder only when feedback exists |
| Separate requested code audit | Matt `code-review` | Coordinator runs the native skill with its full criteria and dispatch procedure |
| Prepare a separate manual review | Superpowers `requesting-code-review` | Coordinator when a separate review is needed; avoid duplicate dispatch |
| Verify completion from fresh evidence | Superpowers `verification-before-completion` | Builder and coordinator before completion claims |
| Preserve work across sessions | Matt `handoff` | Explicit user invocation at a genuine session boundary |
| Improve architecture beyond the current ticket | Matt `improve-codebase-architecture` | Explicit user invocation; separate scoped work |
| Learn from a completed session | Matt `retro` | Explicit user invocation after delivery |

The factory's built-in standards/spec review prompts are its own implementation;
they do not execute Matt code-review or import its full criteria. Use that native
skill for a separate requested audit, not recursively inside factory leaves.

Matt `tdd` and `diagnosing-bugs` are available alternatives to the corresponding
Superpowers disciplines. Choose one per stage; do not stack two TDD/debugging
workflows. The combined inventory profile deliberately requires the Superpowers
TDD, debugging and verification skills. For a Matt-only primary TDD choice,
use the existing `--tdd-skill /actual/path/tdd/SKILL.md` option instead.

EGM owns brainstorming, drafting, five-stage design review and drift checking.
Matt `grill-with-docs` is a classic-workflow alternative for unresolved design,
not an additional compulsory interview after an EGM design is settled. Do not
add Superpowers brainstorming/writing-plans to repeat an approved EGM design.
Do not invoke implement-spec, subagent-driven-development, parallel dispatch,
worktree creation or branch finishing inside factory workers: the factory owns
those operations. Installed plugins may auto-trigger: inspect their actual
instructions and apply the chosen project workflow explicitly. This integration
does not disable plugins or override invocation restrictions.

## Install once per host

For Matt, the upstream currently documents:

```sh
# Claude Code
claude plugin install mattpocock-skills@claude-plugins-official
# Codex CLI
codex plugin marketplace add mattpocock/skills
codex plugin add mattpocock-skills@mattpocock
```

Run the installed `setup-matt-pocock-skills` explicitly for the target project.
Keep the existing issue tracker and documentation conventions when already set.
For Superpowers, use `/plugin install superpowers@claude-plugins-official` in
Claude Code, or find Superpowers through `/plugins` in Codex CLI / Plugins in
Codex App. Restart as required by the installed host. Pick one installation
mechanism per provider per host to avoid duplicate skills. Marketplace versions
may differ from the source revisions linked above.

## Discover and configure actual files

Locate the installed plugin roots, or complete local upstream checkouts. The
scanner supports `skills/engineering/NAME`, `skills/productivity/NAME`,
`skills/NAME`, and `NAME` under each supplied root. It scans only this selected
catalog, not credentials, all plugins, or the user's home directory. Duplicate
matches are rejected. Supply a narrower root to resolve ambiguity.

```sh
python /tools/infra-code-factory/skill_inventory.py \
  --matt-root /installed/mattpocock-skills \
  --superpowers-root /installed/superpowers \
  --output /local-config/factory-skills.json
python /tools/infra-code-factory/configure.py --repo /project \
  --skills-inventory /local-config/factory-skills.json \
  --provider codex --model YOUR_MODEL_ID --egm
# Inspect the preview, then repeat configure.py with --apply.
```

For Claude use `--provider claude --model YOUR_FULL_CLAUDE_MODEL_ID`. Mixed
provider `--route` overrides still work. Do not combine `--skills-inventory`
and `--tdd-skill` in the same command. Both paths preserve project check and
verification policy settings. The inventory does not configure those checks.

The inventory records availability, absolute local paths, each selected skill's
`disable-model-invocation` flag and SHA-256 hashes of all files inside its skill
directory. Required missing skills block configuration; optional missing skills
remain visibly unavailable. Unknown invocation flags, quoted/escaped top-level keys, YAML merge keys and
duplicate keys are rejected rather than interpreted as permission. The scanner
supports simple frontmatter, not every YAML feature. User-only
skills are never automatically injected into worker prompts. Only model-invocable
builder helpers are attached to commands. The full inventory remains in config
for the coordinator to consult; reviewers receive their lens, not orchestrator
skills that would allocate more reviewers.

Config loading checks the inventory against disk. Helpers and their bundled
references also participate in the existing toolchain evidence checks. A plugin
update requires regenerating the inventory, reviewing the configuration change,
and fresh ticket verification. Inventory output files are exclusive-create;
choose a new filename for an update. Paths and hashes are machine-specific:
regenerate on another host. Shared references outside each selected skill folder
are not transitively hashed; keep the complete plugin distribution available.

## Evidence and limits

The test suite exercises both host profiles, invocation restrictions, modified
helper references and real factory dispatch through fake workers. Discovery was
also run against both upstream checkouts at the revisions above. Native host
plugin installation and paid model skill-following were not tested. Skill prompts
can improve discipline; only actual checks and independent review establish the
factory's local READY result.
