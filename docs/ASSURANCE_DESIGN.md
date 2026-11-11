# v0.5 assurance and operations contract

The requested upgrade adds four connected capabilities without weakening the
existing EGM, cold-test, standard/spec review, hold or three-attempt gates.

1. Project-owned `review_policy` chooses additional lenses using the actual Git
   diff (including deletions and both sides of renames). Every selected lens must
   pass in its own cold checkout. Missing configured commands fail before dispatch.
2. An independent read-only risk assessor receives the candidate, base, ticket and
   changed files, not builder transcripts or prior review conclusions. Project
   risk floors and critical-ticket classification can raise its risk. High risk
   can require human review; a passing candidate then waits in AWAITING_HUMAN.
   Local `approve` records an explicit operator attestation tied to candidate,
   risk digest and configuration. It does not authenticate the named human.
3. `repair` accepts only controller-recorded failed code reviews or fetched GitHub
   Actions metadata from allowlisted workflow IDs in the configured repository.
   The caller names the exact candidate SHA. Repair creates a fresh worktree from
   the original base, supplies pinned prior candidate/findings as data, and reruns
   every applicable check/review/risk gate. Each explicit invocation makes one attempt. At most two repairs and three total
   attempts are possible. It never publishes automatically or resets attempt
   history. Published drafts remain historical until explicitly republished;
   this release does not force-push or update the old draft.
4. A read-only terminal event feed and loopback web dashboard show recorded ledger
   states, candidate IDs, holds, risk/human-review state and monotonic event cursors.
   The browser uses local assets, safe text rendering and bounded polling. It has
   no approval/repair/publication endpoints. Live ledger state is not a fresh
   certificate of remote CI or current filesystem verification.

Existing configurations remain supported; an example policy and configure flag
make specialist/risk routing explicit for Claude or Codex. GitHub CI repair needs
an explicit repository/workflow allowlist and the user's existing `gh` access.
Native provider quality/authentication and live GitHub behavior are separate pilot
checks; integration tests use deterministic workers and mocked GitHub responses.
