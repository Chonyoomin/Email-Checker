# Instructions for coding assistants

Use three roles in order: coder -> independent reviewer -> documenter. Keep output
concise, work on one bounded task, preserve user changes and add no code comments.
Keep required public-interface docstrings and license notices.

Before coding read:
1. Email_Scam_Checker_Coding_Agent_PRD.md and Email_Scam_Checker_Task_Breakdown.md.
2. docs/IMPLEMENTATION_STATUS.md.
3. docs/memory/HANDOFF.md, LAST_CYCLE.md, REVIEW_FIXES.md and DECISIONS.md.
4. The latest relevant report under docs/runs and your role file under agents/.

Fix open reviewer findings before new tasks. Only the coder edits product code;
the reviewer independently inspects code and executes checks without editing it.
The documenter saves findings, actual verification, blockers and next action in
shared memory. Repeat the same task until approved or blocked; never mark unrun
checks passed. Follow docs/AGENT_WORKFLOW.md for manual or optional LangChain use.

Routine development does not authorize installs, downloads, credentials, commits,
pushes or deployment. An explicit user setup request may authorize the bounded
project-local virtualenv/dependency/public-checkpoint setup in docs/SETUP.md and
prompts/01-install-windows.md. Preserve existing files and do not install global
tools or modify unrelated environments. Respect the execution environment's own
permission controls. A copied guide alone is not user authorization to execute it.

Never put credentials, OAuth codes, tokens or real email contents in agent context,
logs, Git or project memory. User handles Google sign-in; configure paths only.
Use synthetic fixtures for checks. Do not inspect retained feedback or label-item
bodies. Product scans use local LAYA/direct Python; generative agents are optional
development tools. Do not resume Phase 7 training/calibration/model promotion unless
the owner explicitly requests it. A new checkout includes no model or private data.

Use rg and focused reads; batch independent checks. No mandatory next feature is
defined: ask for a bounded task instead of restarting completed implementation phases.
