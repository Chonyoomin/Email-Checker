# Development agent workflow

## Optional LangChain runner setup

External assistants can use the manual protocol below without LangChain or Ollama.
For the optional automatic runner, first complete the application setup, then
explicitly authorize these additional development dependencies:

```powershell
.\.venv\Scripts\python -m pip install -r requirements-agents.lock
.\.venv\Scripts\python -m pip check
.\.venv\Scripts\python -m pytest tests/test_agent_workflow.py tests/test_langchain_construction.py -q
```

Install/start Ollama separately and choose your own already installed model that
supports tool calls and structured output. The runner downloads no model. Use
`ollama list` to obtain its exact tag, then run a newly owner-scoped task:

```powershell
.\.venv\Scripts\python -m agent_workflow --task YOUR_TASK_ID --model YOUR_INSTALLED_MODEL_TAG
```

Replace both placeholders. Do not automatically rerun completed implementation
tasks or resume deferred Phase 7. The application and development-tool locks are
separate; retain the existing application environment and check for conflicts.

## Automatic cycle

Run from the repository root as shown in README.md. One invocation processes one
task, repeating this order when review requires fixes:

1. **Coder:** reads requirements, phase status and memory, edits product files,
   writes tests, and reports changes. Can read text files, write approved product
   paths, and execute pytest.
2. **Reviewer:** independently reads actual code against PRD and acceptance
   criteria. Can read files and run pytest, but has no file-writing tool. Returns
   structured approval or changes requested, with evidence and findings.
3. **Documenter:** reads both reports, code and check evidence. Has read tools
   only and returns a structured Markdown handoff. The runner writes shared memory
   and per-cycle reports after documentation.

LangChain's `create_agent` handles each role's tool loop. Python coordinates their
fixed order. Failed review automatically sends the documented findings back to the
coder for the same task, followed by another review and documentation. The default
limit is three total cycles; change it with `--max-cycles N`. At the limit the
runner stops with changes requested and retains all open findings for resumption.
The reviewer and documenter use `ToolStrategy` for validated structured responses.
Reference: [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents),
[structured output](https://docs.langchain.com/oss/python/langchain/structured-output),
[ChatOllama](https://docs.langchain.com/oss/python/integrations/chat/ollama).

Exit codes: 0 approved; 2 changes requested; 1 interrupted/error. Failed pytest,
including no collected tests, overrides approval. The step limit bounds each
agent's graph execution; individual model calls time out after 180 seconds and
pytest after 120 seconds. Acceptance requiring browser, Docker, credentials or a
real checkpoint must be checked separately and reported honestly. A green harness
suite alone cannot establish acceptance of a new product feature.

## Shared memory and authority

- PRD: product requirements. Task breakdown: scope and dependency gates.
- `IMPLEMENTATION_STATUS.md`: phase table, reconciled only with gate evidence.
- `memory/LAST_CYCLE.md`: latest workflow outcome and immediate next action;
  **read this before the handoff if a cycle was interrupted or changes requested**.
- `memory/HANDOFF.md`: documenter's working context for the next coder.
- `memory/DECISIONS.md`: durable decisions with dates and rationale.
- `memory/REVIEW_FIXES.md` and `REVIEW_FIXES.json`: persistent fix checklist and
  machine-readable state. Broken code, omitted features and missing checks become
  open findings with IDs. Findings are saved before documentation, sent directly
  to the next coder, and resolved only after reviewer approval. Open findings block
  starting another task, even in a later invocation.
- `runs/<timestamp-id>/REPORT.md` and `report.json`: stage reports, changed-file
  list and real check output, including interrupted cycles.

Task approval never marks an entire phase complete. The automatic runner updates
cycle memory, leaving the phase table conservative. A documenter (including an
external assistant acting in that role) reconciles phase status after reading all
phase gate evidence. Resolve conflicts using code and executed evidence; keep
unverified claims pending. Historical reports are retained rather than overwritten.

## External coding assistants

No LangChain installation is needed for a manual handoff:

1. Read AGENTS.md, required context, LAST_CYCLE.md when present, and relevant run
   reports. Announce the task and act as coder using `agents/coder.md`.
2. Start a fresh review context with `agents/reviewer.md`. Inspect the actual code
   and diff, check every acceptance criterion, execute checks, and save findings.
3. Act as documenter with `agents/documenter.md`. Save code/review/check evidence
   to a new `docs/runs/<unique-id>/REPORT.md`; update HANDOFF.md and LAST_CYCLE.md.
   Update IMPLEMENTATION_STATUS.md only to reflect evidence and append decisions
   if a lasting choice was made. Keep failed tasks open with exact repair steps.
4. If review requests changes, update REVIEW_FIXES.md and REVIEW_FIXES.json
   consistently (preserve IDs and open/resolved status), then return to the coder
   on the same task. Verify every original finding before closing it. Do not start
   the next task while fixes remain open. Existing automatic JSON uses `task` and
   `issues`, each with `id`, `description`, `status`, and `reported_in` fields;
   resolved items also record `resolved_in`. Retain historical reports as evidence.

An external assistant can implement code while a separate model/human reviews it;
separate contexts support independent inspection. Do not run manual and automatic
writers concurrently. The lock only coordinates automatic cycles in this checkout.

## Recovery and operational limits

If a model/tool fails, the runner records the failed stage, retains partial code
and the preceding handoff, and writes LAST_CYCLE.md with recovery instructions.
Inspect the partial changes, then rerun the same task. Do not assume rollback.
After a process is forcibly killed, inspect the newest run and working tree. Remove
`.agent-workflow.lock` only after verifying its recorded PID is no longer running.

Tools limit agent writes and omit credentials/binaries from reads. This is **not an
OS sandbox**: pytest executes repository Python with your permissions. Use trusted
code or an isolated checkout/container. A model can put sensitive text into a
source file or report, so never store real emails or credentials in readable
project text. Reports contain development source and test output and are intended
for version control only after checking that output for sensitive data.

To add product directories or verification commands, deliberately update the
harness allowlist and tests. Agents cannot modify their own harness. Current
automated checks are pytest only; use an external agent for dependency installation,
browser checks, vendor-document verification, and other work requiring extra tools.

## Updating agent dependencies

`requirements-agents.in` declares compatible major versions; the lockfile pins
the full resolved environment. Refresh it deliberately in a clean virtualenv and
rerun both tests and the agent-construction smoke check. The product uses
`requirements.lock` or `requirements-dev.lock`; the optional tooling lock does not
replace them.
