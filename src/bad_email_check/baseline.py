import argparse
import asyncio
import ctypes
import hashlib
import json
import math
import os
import platform
import random
import socket
import time
from contextlib import contextmanager
from pathlib import Path

from .config import Settings
from .evaluation_dataset import validate_dataset
from .extraction import extract_eml
from .metadata_store import MetadataStore
from .scan_service import ScanError, ScanService


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    return values[lower] + (values[math.ceil(position)] - values[lower]) * (position - lower)


def rates(rows):
    tp = sum(row["label"] == 1 and row["predicted"] == 1 for row in rows)
    fp = sum(row["label"] == 0 and row["predicted"] == 1 for row in rows)
    fn = sum(row["label"] == 1 and row["predicted"] == 0 for row in rows)
    tn = sum(row["label"] == 0 and row["predicted"] == 0 for row in rows)
    ap = sum(row["label"] == 1 and row["predicted"] is None for row in rows)
    an = sum(row["label"] == 0 and row["predicted"] is None for row in rows)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "abstained_positive": ap,
        "abstained_negative": an,
        "total": len(rows),
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn + ap) if tp + fn + ap else None,
        "false_positive_rate": fp / (fp + tn + an) if fp + tn + an else None,
        "coverage": (tp + fp + fn + tn) / len(rows) if rows else None,
    }


def wilson(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0, center - radius), min(1, center + radius)]


def uncertainty(rows, repetitions=2000):
    groups = {}
    for row in rows:
        groups.setdefault(row["group_id"], []).append(row)
    generator = random.Random(20261029)
    samples = {key: [] for key in ("precision", "recall", "false_positive_rate", "coverage")}
    identities = sorted(groups)
    for _ in range(repetitions):
        drawn = (
            [
                row
                for identity in generator.choices(identities, k=len(identities))
                for row in groups[identity]
            ]
            if identities
            else []
        )
        values = rates(drawn)
        for key, values_list in samples.items():
            if values[key] is not None:
                values_list.append(values[key])
    observed = rates(rows)
    return {
        "method": "95% percentile bootstrap of complete groups; fixed seed 20261029",
        "groups": len(groups),
        "repetitions": repetitions,
        "cluster_bootstrap": {
            key: {
                "interval": [percentile(values, 0.025), percentile(values, 0.975)]
                if values
                else None,
                "valid_repetitions": len(values),
            }
            for key, values in samples.items()
        },
        "binomial_reference_only": {
            "precision": wilson(observed["tp"], observed["tp"] + observed["fp"]),
            "recall": wilson(
                observed["tp"], observed["tp"] + observed["fn"] + observed["abstained_positive"]
            ),
            "false_positive_rate": wilson(
                observed["fp"], observed["fp"] + observed["tn"] + observed["abstained_negative"]
            ),
        },
    }


def hardware():
    result = {
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "cpu": platform.processor(),
        "physical_ram_bytes": None,
    }
    if os.name == "nt":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            result["cpu"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()

        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong)
                for name in (
                    "total",
                    "available",
                    "total_page",
                    "available_page",
                    "total_virtual",
                    "available_virtual",
                    "extended",
                )
            ]

        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result["physical_ram_bytes"] = memory.total
    elif platform.system() == "Linux":
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                result["physical_ram_bytes"] = int(line.split()[1]) * 1024
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                result["cpu"] = line.split(":", 1)[1].strip()
                break
    return result


@contextmanager
def offline():
    attempts = []
    original_connect, original_create = socket.socket.connect, socket.create_connection

    def denied(*args, **kwargs):
        attempts.append(True)
        raise OSError("Network disabled for baseline inference")

    socket.socket.connect = denied
    socket.create_connection = denied
    try:
        yield attempts
    finally:
        socket.socket.connect, socket.create_connection = original_connect, original_create


def checked_manifest(root, expected_hash):
    if hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest() != expected_hash:
        raise ValueError("Frozen evaluation manifest hash mismatch")
    return validate_dataset(root)


def result_record(record, result, threshold):
    estimate = result.assessment.overall_scam if result.score is not None else None
    return {
        "id": record["id"],
        "group_id": record["group_id"],
        "source": record["source"],
        "label": record["label"],
        "tags": record["tags"],
        "status": result.status,
        "estimate": estimate,
        "predicted": int(estimate >= threshold) if estimate is not None else None,
        "timings": result.timings.model_dump(),
        "runtime": result.runtime.model_dump(),
    }


def summarize(rows):
    public = [row for row in rows if row["source"] != "authored-safety-fixture"]
    synthetic = [row for row in rows if row["source"] == "authored-safety-fixture"]
    warm = [
        row
        for row in rows
        if row["runtime"]["inference_phase"] == "warm" and row["predicted"] is not None
    ]
    performance = {
        "warm_scored_count": len(warm),
        "warm_extraction_p50_ms": percentile(
            [row["timings"]["extraction_ms"] for row in warm], 0.5
        ),
        "warm_extraction_p95_ms": percentile(
            [row["timings"]["extraction_ms"] for row in warm], 0.95
        ),
        "warm_inference_p50_ms": percentile([row["timings"]["inference_ms"] for row in warm], 0.5),
        "warm_inference_p95_ms": percentile([row["timings"]["inference_ms"] for row in warm], 0.95),
        "warm_pipeline_p50_ms": percentile([row["timings"]["total_ms"] for row in warm], 0.5),
        "warm_pipeline_p95_ms": percentile([row["timings"]["total_ms"] for row in warm], 0.95),
        "first_inference_ms": [
            row["timings"]["inference_ms"]
            for row in rows
            if row["runtime"]["inference_phase"] == "first"
        ],
        "max_process_peak_rss_bytes": max(
            (row["runtime"]["process_peak_rss_bytes"] or 0 for row in rows), default=0
        ),
    }
    performance["warm_pipeline_p95_under_3_seconds"] = (
        performance["warm_pipeline_p95_ms"] is not None
        and performance["warm_pipeline_p95_ms"] < 3000
    )
    return {
        "public": {"metrics": rates(public), "uncertainty": uncertainty(public)},
        "synthetic_safety": {
            "metrics": rates(synthetic),
            "cases": [
                {"tags": row["tags"], "status": row["status"], "predicted": row["predicted"]}
                for row in synthetic
            ],
        },
        "performance": performance,
    }


async def evaluate(root, expected_hash, output, checkpoint, threshold):
    manifest = checked_manifest(root, expected_hash)
    if (output / "results.json").exists():
        raise ValueError("Choose a new output directory; previous predictions are preserved")
    output.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        checkpoint_path=checkpoint,
        gmail_client_file=None,
        cache_entries=0,
        metadata_db_path=output / "metadata.sqlite3",
    )
    service = ScanService(settings)
    store = MetadataStore(settings.metadata_db_path)
    store.initialize()
    selected = [record for record in manifest["records"] if record["split"] == "test"]
    report = {
        "complete": False,
        "manifest_sha256": expected_hash,
        "threshold": threshold,
        "threshold_policy": (
            "Predeclared raw uncalibrated estimate >= 0.5, no test-set tuning; "
            "no UI risk-band change"
        ),
        "hardware": hardware(),
        "records": [],
    }
    report["code_sha256"] = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in (
            "baseline.py",
            "laya_adapter.py",
            "questions.py",
            "extraction.py",
            "scan_service.py",
        )
    }
    report["runtime_lock_sha256"] = hashlib.sha256(
        Path("requirements.lock").read_bytes()
    ).hexdigest()
    with offline() as attempts:
        try:
            await service.start()
            if service.adapter is None:
                raise RuntimeError("Real model is not ready")
            report.update(
                model_identity=service.adapter.identity.__dict__,
                model_load_ms=service.model_load_ms,
                context_tokens=service.adapter.context_limit,
                head_tokens=service.adapter.head_limit,
            )
            import torch

            report["hardware"].update(
                torch=torch.__version__,
                torch_threads=torch.get_num_threads(),
                cpu_only=str(service.adapter.agent.device) == "cpu",
            )
            for index, record in enumerate(selected):
                started = time.monotonic()
                evidence = extract_eml((root / record["path"]).read_bytes(), settings)
                extraction_ms = (time.monotonic() - started) * 1000
                result = await service.scan(evidence, started, extraction_ms)
                report["parser_version"] = result.parser_version
                store.record(result, "eml")
                report["records"].append(result_record(record, result, threshold))
                (output / "results.json").write_text(json.dumps(report, indent=2))
                print(
                    json.dumps(
                        {
                            "completed": index + 1,
                            "total": len(selected),
                            "status": result.status,
                            "elapsed_seconds": round(time.monotonic() - started, 3),
                        }
                    ),
                    flush=True,
                )
            report["prediction_calls"] = service.adapter.assess_calls
        finally:
            service.close()
        report["network_attempts"] = len(attempts)
    if report["network_attempts"]:
        raise RuntimeError("Baseline attempted network access")
    report["complete"] = True
    report["summary"] = summarize(report["records"])
    (output / "results.json").write_text(json.dumps(report, indent=2))
    (output / "summary.json").write_text(
        json.dumps({key: value for key, value in report.items() if key != "records"}, indent=2)
    )
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Run one offline prediction per frozen held-out example."
    )
    parser.add_argument("--dataset", type=Path, default=Path("data/evaluation"))
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, default=Path("data/baseline"))
    parser.add_argument("--checkpoint", type=Path, default=Path("checkpoints/laya-english"))
    args = parser.parse_args()
    try:
        report = asyncio.run(
            evaluate(args.dataset, args.manifest_sha256, args.output, args.checkpoint, 0.5)
        )
    except OSError, ValueError, RuntimeError, ScanError:
        print("Baseline stopped; inspect non-content partial metrics and setup before retrying.")
        raise SystemExit(2) from None
    print(
        json.dumps(
            {
                "complete": report["complete"],
                "records": len(report["records"]),
                "network_attempts": report["network_attempts"],
            }
        )
    )


if __name__ == "__main__":
    main()
