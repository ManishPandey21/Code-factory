# Applying Karpathy's views

This is a factory design interpretation, not an endorsement by Andrej Karpathy and not a copied community “Karpathy skills” package.

Primary sources reviewed:

- https://karpathy.ai/ — links to his own writing and accounts.
- https://karpathy.bearblog.dev/verifiability/ — argues that resettable, efficient and objectively verifiable tasks are especially amenable to AI progress.
- https://karpathy.bearblog.dev/sequoia-ascent-2026/ — his published talk summary describes the programmer increasingly orchestrating larger agent actions. He explicitly labels the summary/transcript as AI-generated and says he reviewed it.

Applied here:

| Published theme | Our implementation choice |
|---|---|
| Verifiability matters | Every ticket declares observable acceptance criteria; configured checks and independent review determine completion |
| Resettable attempts | Isolated worktrees preserve the baseline and make a failed attempt inspectable |
| Orchestration of larger actions | One coordinator delegates a complete vertical ticket rather than issuing tiny file edits |
| Context and tools affect outcomes | Pass a bounded task, applicable instructions and one primary skill rather than all available skills |
| Capabilities remain uneven | Explicitly report missing evidence and escalate consequential ambiguity; a model's confidence does not pass a gate |

Additional factory engineering rules: state assumptions before consequential decisions; choose the smallest implementation that meets the accepted spec; avoid unrelated refactoring; inspect actual diffs and test assertions. These are our safeguards, not quotations attributed to Karpathy. We do not treat a third-party repository bearing his name as his official guidance.
