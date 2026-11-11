# v0.4.1 validation — 11 November 2026

Changes: selected Matt Pocock/Superpowers inventory, conditional builder helpers,
Claude/Codex configuration, and coordinator workflow guidance.

- Eight new inventory/configuration/dispatch tests pass.
- Four existing portability tests and 25 routing tests pass.
- Full suite: **150 tests passed** in 240.064 seconds; no failures or skips.
- Real upstream discovery: all 18 selected skills found at the revisions linked
  in SKILL_PROFILES.md. User-only flags were detected for setup, interviews,
  ticket decomposition, architecture survey, retro and handoff.

The real-Git integration test verifies that builder prompts receive conditional
helper paths, reviewer prompts do not receive the builder helper block, and a
changed reference file blocks subsequent run/publication commands. Other tests
cover both provider profiles, preserving checks in preview, missing required
skills, ambiguous installation roots, helper invocation restrictions and
unsupported/duplicate frontmatter keys.

Independent code and requirement reviews found an invocation-parser edge case,
a missing explicit-invocation qualification for handoff, and an overstatement
of native Matt code-review integration. These were corrected and both reviewers
verified their fixes. Factory code review remains its own two-lens mechanism;
native Matt code-review is available for separate requested audits.

These are orchestration and discovery tests with fake workers. No paid model
skill-following or native host plugin installation was tested. Marketplace
versions can change; regenerate the inventory after plugin updates.
