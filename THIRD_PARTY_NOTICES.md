# Licensing and third-party components

No project LICENSE file was present in the source repository, and this export does
not assign a new project license. The repository owner selects the license before
distributing it under specific license terms. Existing dependency and attribution
notices are retained.

- LAYA inference/training tooling: https://github.com/NandhaKishorM/laya
- Public checkpoint: https://huggingface.co/convaiinnovations/laya
  Revision and file hashes are recorded in `src/bad_email_check/laya_checkpoint.json`.
  The model weights and model card are downloaded separately, not bundled here.
- Python dependency versions are pinned in the lockfiles. Each dependency retains
  its own license and package notices.
- Optional evaluation corpus sources and their attribution are documented in
  [the dataset guide](docs/EVALUATION_DATASET.md). No corpus or real messages ship here.
- Test `.eml` files are authored synthetic fixtures, not exported mailbox messages.

GitHub publication, a project license choice and any checkpoint/data redistribution
are separate owner actions. This preparation does not publish or relicense them.
