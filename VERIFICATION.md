# Verification

Verified on Windows on 2026-10-21:

- Fresh Python 3.14 virtual environment installed from `requirements.txt`; all 12 helper tests passed.
- Both CLI help and encrypted-session check ran from that fresh environment. A live candidate-documents read succeeded through the packaged HTTP client.
- The installed official connector reported Connected in Claude Code; official account/profile reads and a source-backed profile update succeeded in Codex.
- A genuine, user-confirmed master-CV title correction was proposed by Jack and accepted through the corrected helper. Acceptance created new version/thread IDs. A fresh API read found the exact unchanged suggestion at its new ID with terminal `accepted` status; another independent read confirmed the saved title and ready CV. Only the intended title/team identifier changed.
- Empty-string deletions, rejection, ambiguous snapshots, pending proposed text and 409 reconciliation were verified with deterministic tests. No fake candidate facts were inserted into a live account for testing.

Private candidate IDs, CVs, requests, session files and acceptance receipts remain outside this repository. They are deliberately absent here.

Limits: this is not a fresh-account OAuth test on both hosts, a complete employer application test, a rendered-layout certification for any resume, or a measured per-application allowance benchmark. Website API compatibility is verified for the observed calls, not every possible editor operation. Further runtime changes require renewed checks.
