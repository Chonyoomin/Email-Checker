# Contributing

Read [AGENTS.md](AGENTS.md), the [requirements](Email_Scam_Checker_Coding_Agent_PRD.md)
and current shared memory before making changes. Scope one task, implement it,
obtain independent review, then document executed checks and the next action.

Run the [verification commands](README.md#verify). Keep real-model checks explicitly
opt-in and separate from fast tests. Use synthetic messages in tests and reports.
Do not commit local settings, credentials, retained email, databases or weights.

Describe the behavior changed, the verification actually run, unrun checks and any
remaining findings. Preserve model-quality limits and no-score behavior. Optional
training requires a separate owner request and verified, versioned data.
