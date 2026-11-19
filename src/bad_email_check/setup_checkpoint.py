import argparse
import json
import os
from pathlib import Path

from .laya_adapter import CHECKPOINT_ID, CHECKPOINT_REVISION, verify_checkpoint


def main():
    parser = argparse.ArgumentParser(
        description="Explicitly download the pinned local LAYA checkpoint."
    )
    parser.add_argument("--directory", type=Path, default=Path("checkpoints/laya-english"))
    args = parser.parse_args()
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HOME"] = str(args.directory.resolve().parent / "hf-cache")
    from huggingface_hub import snapshot_download

    manifest = json.loads(
        Path(__file__).with_name("laya_checkpoint.json").read_text(encoding="utf-8")
    )
    snapshot_download(
        CHECKPOINT_ID,
        revision=CHECKPOINT_REVISION,
        token=False,
        local_dir=str(args.directory),
        allow_patterns=list(manifest["files"]),
        max_workers=4,
    )
    verify_checkpoint(args.directory)
    print("Pinned checkpoint downloaded and SHA-256 verified. Runtime inference needs no network.")


if __name__ == "__main__":
    main()
