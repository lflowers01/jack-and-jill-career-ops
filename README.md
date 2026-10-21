# Jack & Jill + Career Ops

A reusable skill for **Codex and Claude Code**, plus Windows request helpers for Jack's CV simulator, recommendation decisions and DOCX downloads. Job search uses Jack's official remote MCP. All resume wording stays in Jack; Career Ops handles source facts, evaluation and application preparation.

This is an independent integration, not an official Jack & Jill SDK. The official MCP does not expose CV tailoring; the supplemental helpers follow observed website APIs, which may change. No account, candidate data, cookies, resumes or credentials are bundled. No paid service is added; Jack account access and the agent's own allowance remain separate requirements.

## Agent installation instructions

Prerequisites: Windows, Python 3.10+, Node.js, an existing Career Ops checkout and candidate sources, and an existing Jack & Jill account. Classic desktop Outlook is optional for reading a sign-in code; it is not required for manual email-code login. This version uses Windows DPAPI and does **not** support macOS/Linux, including Claude Code in WSL. Use native Windows Claude Code or Codex.

1. Clone this repository to a local folder. Inspect its scripts and the destination's existing skill/config before installation. Merge existing settings; do not overwrite unrelated configuration or existing skills. Never copy another person's session files or candidate records.
2. From the package directory, create a dedicated environment:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m unittest discover -s skills/jack-and-jill/scripts -p test_jack.py -v
   .\.venv\Scripts\python.exe skills/jack-and-jill/scripts/jack.py --help
   ```

3. Install `skills/jack-and-jill` as a skill folder in the chosen host's user skill directory: `$HOME/.codex/skills/jack-and-jill` for Codex, `$HOME/.claude/skills/jack-and-jill` for Claude Code. Alternatively use the host's project skill directory in Career Ops. Copy the complete folder, including scripts and references. If it already exists, inspect and merge it rather than blindly replacing it. Keep this package venv path for running the scripts. A host restart/new conversation may be needed for skill discovery.
4. Inspect existing MCP entries before adding the official candidate server. Reuse a correct existing entry rather than making duplicates:

   ```powershell
   codex mcp list
   codex mcp add jack-and-jill --url https://platform.jackandjill.ai/mcp/jack/v1/
   codex mcp login jack-and-jill

   claude mcp list
   claude mcp add --transport http --scope user jack-and-jill https://platform.jackandjill.ai/mcp/jack/v1/
   ```

   Complete the host's normal OAuth consent flow. In Claude Code, open `/mcp` and authenticate Jack if it is not connected. Check with `claude mcp get jack-and-jill`. This account connection requires the account owner's consent; installation instructions do not grant it. Use Jack's [official candidate quickstart](https://platform.jackandjill.ai/jack-quickstart.md) if its setup changes.
5. Authenticate the separate website CV helper using the account owner's email. Replace the placeholders; do not store codes in a repository:

   ```powershell
   .\.venv\Scripts\python.exe skills/jack-and-jill/scripts/login.py --email YOUR_EMAIL
   .\.venv\Scripts\python.exe skills/jack-and-jill/scripts/login.py --code SIX_DIGIT_CODE
   .\.venv\Scripts\python.exe skills/jack-and-jill/scripts/login.py --check
   ```

   Optionally use `--email YOUR_EMAIL --outlook` to read the normal sign-in code from the matching default Outlook mailbox's Inbox/Junk. No email is sent by the helper; requesting login causes Jack to send its standard verification email. MFA or additional challenges may require the owner. Session and pending-login state are DPAPI encrypted under `%LOCALAPPDATA%/career-ops/jack-and-jill/`, for the current Windows user. Do not commit or transfer that folder. Official OAuth remains in each host's own credential store.
6. Set the Career Ops repository in the current shell, or simply run scripts from that repository:

   ```powershell
   $env:CAREER_OPS_REPO = 'C:\path\to\career-ops'
   ```

   This is the source-code checkout containing `path-resolver.mjs`. Its usual `CAREER_OPS_ROOT`, `CAREER_OPS_DATA_DIR` and `.career-ops-data` rules still resolve candidate data. Do not change shell startup files to install this workflow. Add a brief instruction in the project's existing agent instructions to use the installed `jack-and-jill` skill for Jack searches and resumes if automatic discovery is insufficient.
7. Read the skill and its [request workflow](skills/jack-and-jill/references/workflow.md). Verify an official `get_account_status` call and a website `documents`/`cv` read. Use source-backed candidate work for the first real simulation and decision; do not insert fake experience as a test. Check every recommendation, downloaded text and rendered layout before an application. Submission remains controlled by the user's authorization.

## What is verified

The helper suite covers session encryption/host boundaries, streamed completion without resending, exact simulator receipt matching, export gates, valid empty-string deletions, explicit rejection, cloned thread-ID matching and 409 read-back behavior. A raw DOCX can already display proposed changes: the connector checks actual decision status instead of treating visible text as acceptance.

Automated tests use fake documents and HTTP transports and do not sign in, spend Jack simulation allowance or mutate an account. Run them after changes. An installation test is not a complete application test. Additional live verification findings belong in [VERIFICATION.md](VERIFICATION.md).

## Limits

- Windows only; credentials are tied to the current Windows user. This is not a hosted remote MCP replacement.
- Jack controls AI latency, service limits and private API changes. A sent marker prevents automatic duplicate chat requests; preserve it on a timeout and inspect the current turn instead of retrying blindly.
- Resume downloading requires a successful exact-job simulator receipt and no open/orphaned recommendations. Fact and layout review remain required; passing tests does not certify candidate content.
- Usage percentages are shared-account, rounded observations. Measure full routine workflows separately from development/testing; do not equate token counts with allowance percentages or promise a fixed application count.
- The package includes no employer-specific application automation and never submits an application by itself. Use Career Ops with an available cheaper browser worker and the user's submission authorization.
