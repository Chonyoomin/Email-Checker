# Phase 7 training tool verification

Use the installed upstream LAYA **0.4.15** Python tooling on the already pinned
English checkpoint. No additional package, checkpoint download or hosted service
is needed for this path. The machine currently has CPU Torch and no CUDA device.

The chosen objective is **supervised cross-entropy**, explicitly
`TrainConfig(loss="soft-ce")`. Upstream's default `rlcd` adds a noisy policy-gradient
term; it is a different objective and must not be selected implicitly. CPU runs
can freeze the encoder and update only the decision head, with AMP and gradient
checkpointing disabled. This establishes feasibility, not sufficient data or quality.

The marked `tests/product/test_training_tools.py` spike loads the hash-verified
local checkpoint, prepares two authored known-label items plus an unresolved item,
performs one supervised optimizer update, saves a temporary checkpoint, and reloads
it through `Agent`. It blocks network connections, verifies the baseline artifacts
remain unchanged, and never activates the temporary checkpoint. It does not use
public provider labels, Gmail, retained feedback or a production candidate.

Unknown labels and the four unlabeled indicator questions are not converted to
negative targets. Only `overall_scam` has synthetic targets in this tool spike.
Changing a shared decision head may affect other questions; later candidate checks
must preserve the full five-question output contract and document indicator limits.

## Integration constraints

- Use `train_model` with explicitly prepared split membership, then an explicit
  export. Avoid `finetune`'s automatic random calibration split and automatic
  temperature/abstention fitting for this project's grouped held-out workflow.
- Upstream training tokenization can truncate state. A project training wrapper
  must preflight the complete canonical evidence and question sequences, just as
  inference does. Do not silently train on a partial email.
- Keep the questions and 2,048/head-192 runtime sequence policy fixed. Preserve
  baseline weights and hashes; a candidate needs separate provenance and approval.
- Task 7.2 requires independently verified labels. Phase 6's source-label proxies
  and unknown rows do not become verified labels through this spike.
- Freeze candidate settings before an independent final test. Phase 6's published
  test outcomes must not be reused as an unseen final test after tuning decisions.
- A calibration fit on a tiny validation slice does not establish probability
  reliability. Calibration and UI probability/risk-band activation remain gated.

Upstream references checked for task 7.1:
[training documentation](https://github.com/NandhaKishorM/laya/blob/main/docs/finetune.md),
[training implementation](https://github.com/NandhaKishorM/laya/blob/main/laya/train.py).
Local installed source/version and executed checks take priority over current-main
examples. LayaStudio's current MLX/Apple-silicon path is not needed on this Windows
CPU environment: [project](https://github.com/biplovgautam/LayaStudio).

Historical verification refers to the original development workspace. Its run
archive, local data and checkpoints are not bundled. See [project history](PROJECT_HISTORY.md).
