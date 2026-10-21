# Direct CV requests

These helpers target Windows and Python 3.10+ with `httpx` and `pywin32`. Official MCP OAuth and website CV sessions are separate. Run from Career Ops or set `CAREER_OPS_REPO` to its repository. Candidate data-root overrides remain owned by Career Ops' path resolver.

Set `$jackPython` to the package venv Python and `$jackScript` to this skill's `scripts/jack.py`. Use absolute paths in retained workers.

```powershell
& $jackPython $jackScript documents --result output/jack-documents.json
& $jackPython $jackScript cv --source SOURCE_ID --result output/jack-source.json
& $jackPython $jackScript job --job JOB_ID --result output/jack-job.json
& $jackPython $jackScript simulate --job JOB_ID --version SOURCE_VERSION --message-id NEW_UUID --result output/jack-simulation.json
& $jackPython $jackScript cv --job JOB_ID --result output/jack-review.json
```

Create the `output` directory before using result paths. IDs above are placeholders; discover the actual candidate source and exact job first. A simulation succeeds only when the saved result contains `simulation` with the exact job/source, successful simulator output and a review ID.

## Decisions

Review every `threads` entry against primary facts. Write `{"thread": FULL_REVIEWED_THREAD_OBJECT}` to a UTF-8 JSON file, preserving the exact full object from the current read, then:

```powershell
& $jackPython $jackScript accept --job JOB_ID --thread THREAD_ID --input output/reviewed-edit.json --result output/accepted.json
& $jackPython $jackScript reject --job JOB_ID --thread THREAD_ID --input output/reviewed-edit.json --result output/rejected.json
```

Use `--source SOURCE_ID` instead of `--job` for master-CV decisions. `after: ""` is a valid deletion; null/missing `after` is not an edit. Reject unsupported open/orphaned suggestions; do not accept a false claim to clear a checkbox. `{ "after": "exact reviewed text" }` also works, but cannot safely remap cloned thread IDs. A full snapshot permits remapping only an exact unique unchanged edit. Changed or ambiguous snapshots fail closed.

For a role comment or inaccurate proposal, put verified source context in a UTF-8 file and ask Jack to produce a supported edit:

```powershell
& $jackPython $jackScript refine --job JOB_ID --thread THREAD_ID --input output/verified-facts.txt --message-id NEW_UUID --result output/refinement.json
```

Review and decide the new edit, then re-read the current CV. For a comment with no supported change, record the source-backed resolution or unresolved factual gap using `resolve-note` and a JSON `reason` of at least 30 characters. That command resolves comments only, never fabricated edits. It currently requires a current role thread ID; inspect state after a conflict instead of retrying.

The DOCX text is a **proposed final view**: tracked edits may already appear before acceptance. Only actual terminal thread status confirms a decision. Decisions can clone CV versions/thread IDs. On HTTP 409, accept/reject reads once and confirms only an actual terminal status; it never resends automatically. Do not mark success because the proposed words appear in the document.

## Export and recovery

```powershell
& $jackPython $jackScript download --job JOB_ID --simulation output/jack-simulation.json --result output/download.json
```

Export refuses unfinished CVs, open/orphaned notes, mismatched simulator reviews and different existing bytes at the same version path. Outputs go to the resolved Career Ops data root under `output/jack-and-jill/JOB/VERSION.docx`, with a hash/text receipt. Render and verify layout before delivery. Enforce candidate-specific banned text from Career Ops custom rules. The scripts do not submit applications.

Jack's AI may take minutes; reads are usually faster. Retain the full shell result/session ID and poll that process. A `.sent.json` marker preserves the request UUID. A timeout or missing result means delivery is uncertain, not permission to resend. Inspect `chat-status`, current CV and retained results first. Never rerun completed simulations just to recover an observation handle. HTTP mutations are not automatically retried.

Website APIs are unofficial and may change. They use only fixed Jack API and Clerk origins; tokens and pending login state are Windows-user DPAPI encrypted. Do not print or commit these files, copy browser cookies or bypass challenges. Official MCP credentials stay in host-managed OAuth storage. Review conflicts and service changes rather than suppressing errors.
