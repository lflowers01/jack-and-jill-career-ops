# Verification

## Workflow reliability fixes — 2026-10-21

- 25 tests pass in the package environment. Added cases cover a real HTTP/SSE transport disconnect with durable received events, incomplete streams and missing simulator receipts failing without a resend, read-only `run-status`, grouped master-source refinements, comment reply/decision reconciliation, timeout recovery without duplicate writes, candidate-policy rejection before export, and unknown thread statuses.
- Live API checks established the distinct terminal states: suggestions are `accepted`/`rejected`; completed comments are `resolved`. A genuine source-backed comment resolution was written and confirmed by a fresh read. Recovery from an earlier unconfirmed decision reconciled the resolved state with exactly one saved reply, and a second genuine resolution passed the complete reply/read/decide/read path. No fabricated candidate fact was inserted for testing.
- The actual earlier rejected resume text is blocked by the candidate's private work-authorization exclusion. Ordinary team fundraising/sponsorship text remains allowed. The generic package contains only opt-in policy support; private candidate restrictions and receipts remain outside Git.
- Routine mutations now use one guarded CLI, including source-CV and grouped refinements. Worker instructions require full shell-result retention, same-handle polling, durable recovery, a per-role evidence checklist and escalation after two equivalent failures without new evidence. A cheaper worker's observed live calls retained full shell results.
- A cheaper worker completed a real existing-role continuation: reused its matching simulator receipt, sent one grouped refinement through the new durable stream path, confirmed the resulting suggestion's accepted state after its ID changed, downloaded the final Jack DOCX with private policy checks, and converted it to a one-page PDF without rewriting content. PDF text matched the download receipt; both worker and coordinator inspected the rendered page. The coordinator independently checked document/text hashes and the active policy. An unsupported scope clause caught at final review was corrected by Jack and the earlier export explicitly marked superseded in the private run report. No search/simulation was redundantly restarted and no employer application was submitted.
- An independent read-only review found an export gap for unknown thread statuses. It was fixed with kind-specific terminal checks and a regression test; targeted re-review found no further concrete issue in those changed paths.

Interrupted/ambiguous operations are intentionally left for inspection rather than automatically retried. The tests and live checks establish these specific behaviors, not an absence of all possible future service or agent errors.

## Initial installation verification

Verified on Windows on 2026-10-21:

- Fresh Python 3.14 virtual environment installed from `requirements.txt`; all 12 helper tests passed.
- Both CLI help and encrypted-session check ran from that fresh environment. A live candidate-documents read succeeded through the packaged HTTP client.
- The installed official connector reported Connected in Claude Code; official account/profile reads and a source-backed profile update succeeded in Codex.
- A genuine, user-confirmed master-CV title correction was proposed by Jack and accepted through the corrected helper. Acceptance created new version/thread IDs. A fresh API read found the exact unchanged suggestion at its new ID with terminal `accepted` status; another independent read confirmed the saved title and ready CV. Only the intended title/team identifier changed.
- Empty-string deletions, rejection, ambiguous snapshots, pending proposed text and 409 reconciliation were verified with deterministic tests. No fake candidate facts were inserted into a live account for testing.

Private candidate IDs, CVs, requests, session files and acceptance receipts remain outside this repository. They are deliberately absent here.

Limits: this is not a fresh-account OAuth test on both hosts, a complete employer application test, a rendered-layout certification for any resume, or a measured per-application allowance benchmark. Website API compatibility is verified for the observed calls, not every possible editor operation. Further runtime changes require renewed checks.
