# Unreleased local hardening validation

Baseline: `4e46acb` (v0.5.0). Changes remain local and unpublished.
The full audit disposition is in [LOCAL_HARDENING.md](LOCAL_HARDENING.md).

## Checks

The first integration pass completed 196 tests successfully; a subsequent pass
with the additional routing, SQL and display changes completed 199 successfully.
The final frozen run adds the repository-alias and alternate temporary-root
regressions: **201 tests passed in 228.024 seconds**, no failures or skips.
Full output: [VALIDATION_HARDENING.log](VALIDATION_HARDENING.log).

Twenty focused tests cover custom wrapper edits, base-only deleted inputs,
relative/absolute/worktree and attached-option path forms, directory/rename
protection, root aliases in both check sources, Git version suffixes and old or
missing Git, pre-allocation failures, controlled malformed API responses,
UTF-8 prompt transport in an ASCII locale, report aliases, internal links,
simulated Windows reparse points, legacy pinned model IDs, SQL column rejection
and the current configured attempt limit.

The optional Chromium/Playwright smoke check passed using:

```sh
python tests/browser_smoke.py --browser /usr/bin/chromium --artifacts /tmp/hardening-browser
```

It verifies the configured `1 / 2` display, safe ticket text, filtering,
desktop/mobile rendering, live hold/event updates and reconnect without duplicate
events. Python compilation, JavaScript syntax and Git whitespace checks passed.

## Independent review

Separate standards and specification reviewers inspected the immutable staged
tree `66b5a4d` against the baseline. Both found that absolute wrapper paths through
a legitimate root alias escaped protection. The fix resolves only the trusted
root prefix and preserves descendant components, including deleted wrapper names.

Both reviewers rechecked staged tree `b3ee1ffd` and independently reproduced the
correct rejection of aliased wrapper modifications/deletions. Neither reported
remaining findings in the follow-up scope. They did not run the full suite; the
coordinator ran it.

## Boundaries

Tests ran on Linux, Python 3.12.14 and Git 2.52.0, with deterministic workers and mocked GitHub API responses.
Temporary-root aliases and Windows reparse metadata were simulated. This is not
a native macOS/Windows pilot, a live-provider quality test, authenticated human
approval, OS isolation or signed verification. The production release blockers
in AUDIT.md remain open. No GitHub rulesets, external identities or signing service
were deployed, and no repository or environment was published by this work.
