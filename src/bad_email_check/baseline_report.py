import argparse
import json
from pathlib import Path


def percentage(value):
    return "undefined" if value is None else f"{100 * value:.1f}%"


def interval(value):
    return "undefined" if value is None else f"{percentage(value[0])} to {percentage(value[1])}"


def seconds(value):
    return "unavailable" if value is None else f"{value / 1000:.3f} s"


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def render(report):
    if not report["complete"]:
        raise ValueError("A partial run cannot be published as a completed baseline")
    summary = report["summary"]
    m = summary["public"]["metrics"]
    u = summary["public"]["uncertainty"]
    p = summary["performance"]
    h = report["hardware"]
    identity = report["model_identity"]
    attacks = [
        row
        for row in report["records"]
        if row["source"] == "authored-safety-fixture"
        and row["label"] == 1
        and row["predicted"] is not None
    ]
    missed = sum(row["predicted"] == 0 for row in attacks)
    sections = [
        f"""# Exploratory baseline evaluation

This small, redacted historical set does not establish accuracy for current Gmail.
At the fixed {report["threshold"]} evaluation cutoff, public phishing recall was
{percentage(m["recall"])}: {m["fn"]} of {m["tp"] + m["fn"]} scored source-positive emails
fell below the cutoff. {missed} of {len(attacks)} scored synthetic deception cases
also fell below it. These results do not support relying on the score to establish legitimacy.

## Frozen inputs and execution

- Dataset manifest SHA-256: `{report["manifest_sha256"]}`.
- Held-out records: {len(report["records"])}; train/validation were not predicted.
- Completed real prediction calls: {report["prediction_calls"]}; one model reused; cache disabled.
- Guarded network attempts: {report["network_attempts"]} during loading/scans.
- Fixed raw-estimate cutoff: {report["threshold"]}; no tuning, calibration or new UI risk band.
- Checkpoint: `{identity["checkpoint_revision"]}`.
- Adapter: `{identity["adapter_version"]}`; questions: `{identity["question_set_version"]}`.
- Parser: `{report["parser_version"]}`.
- Input context: {report["context_tokens"]} tokens; head: {report["head_tokens"]}.

## Public-corpus results

Enron non-spam is a proxy for legitimate; Nazario provides source-labeled phishing.
These labels were not newly adjudicated. Synthetic cases are excluded from this table.
"""
    ]
    sections.append(
        table(
            ["True source label", "Predicted phishing", "Predicted negative", "Abstained/no score"],
            [
                ["Phishing", m["tp"], m["fn"], m["abstained_positive"]],
                ["Non-spam proxy", m["fp"], m["tn"], m["abstained_negative"]],
            ],
        )
    )
    names = {
        "precision": "Precision",
        "recall": "Phishing recall",
        "false_positive_rate": "Operational false-alert rate",
        "coverage": "Scored coverage",
    }
    sections.append(
        table(
            ["Metric", "Point estimate", "Group-bootstrap 95% interval"],
            [
                [name, percentage(m[key]), interval(u["cluster_bootstrap"][key]["interval"])]
                for key, name in names.items()
            ],
        )
    )
    conditional = m["fp"] / (m["fp"] + m["tn"]) if m["fp"] + m["tn"] else None
    references = "; ".join(
        key + " " + interval(value) for key, value in u["binomial_reference_only"].items()
    )
    sections.append(f"""
Precision = TP/(TP+FP). Recall includes positive abstentions in its denominator.
Operational false-alert rate = FP/(FP+TN+negative abstentions), over ALL source negatives.
Conditional false-positive rate on scored negatives, FP/(FP+TN), is {percentage(conditional)}.
Abstentions never silently become correct negative predictions.

Intervals resample {u["groups"]} complete public groups {u["repetitions"]} times, seed 20261029.
Small-sample percentile intervals can degenerate at 0%/100%; that does not establish
zero error or certainty. Wilson reference intervals assume independent emails and
are NOT cluster-correct: {references}.

## Synthetic safety cases

These authored cases test behavior; they are not pooled with public examples for accuracy.
""")
    cases = []
    for row in report["records"]:
        if row["source"] != "authored-safety-fixture":
            continue
        decision = (
            "no score"
            if row["predicted"] is None
            else ("phishing" if row["predicted"] else "negative")
        )
        cases.append(
            [
                ", ".join(row["tags"]),
                "deception" if row["label"] else "legitimate",
                row["status"],
                decision,
            ]
        )
    sections.append(table(["Case", "Intended fixture label", "Status", "Decision"], cases))
    sections.append(f"""
Long inputs withhold scores. The malformed missing-header fixture fails extraction.
Other scored fixture decisions are measured model behavior, not legitimacy assurances.

## Hardware and timing

{h["cpu"]}; {h["logical_cpus"]} logical CPUs; {h["os"]} {h["os_release"]}; {h["architecture"]}.
Python {h["python"]}; Torch {h["torch"]}; {h["torch_threads"]} Torch threads; CPU inference.
Physical RAM: {h["physical_ram_bytes"]} bytes. Logical model tensor bytes:
{report["records"][0]["runtime"]["model_tensor_bytes"]}. Peak process RSS:
{p["max_process_peak_rss_bytes"]} bytes, including Python/dependencies and all scans.
""")
    sections.append(
        table(
            ["Measurement", "Observed"],
            [
                ["Cold verification/load", seconds(report["model_load_ms"])],
                ["First inference", ", ".join(seconds(value) for value in p["first_inference_ms"])],
                ["Warm scored count", p["warm_scored_count"]],
                [
                    "Warm model-stage p50 / p95",
                    seconds(p["warm_inference_p50_ms"])
                    + " / "
                    + seconds(p["warm_inference_p95_ms"]),
                ],
                [
                    "Warm extraction p50 / p95",
                    seconds(p["warm_extraction_p50_ms"])
                    + " / "
                    + seconds(p["warm_extraction_p95_ms"]),
                ],
                [
                    "Warm pipeline p50 / p95",
                    seconds(p["warm_pipeline_p50_ms"]) + " / " + seconds(p["warm_pipeline_p95_ms"]),
                ],
            ],
        )
    )
    target = "met" if p["warm_pipeline_p95_under_3_seconds"] else "NOT met"
    sections.append(f"""
The initial warm p95 <3-second engineering target was **{target}** in this sample.
Model-stage time dominates extraction; no kernel-level cause was profiled.
Warm statistics include scored warm runs only, excluding first inference, cache hits
and extraction/context abstentions. Cold load is separate. Pipeline total excludes
metadata persistence, response serialization and browser overhead. HTTP/browser/Gmail
retrieval p95 was not measured. Short redacted cases do not characterize every input
up to the 2,048-token boundary. Single cold/first samples are not latency guarantees.

## Limits and next action

Source age, balanced short-input sampling, provider-label uncertainty, redaction and
plaintext wrapper changes limit transfer to current mail and deployment prevalence.
Precision depends on prevalence. Grouping cannot prove separation from unknown campaigns
or from the checkpoint's undisclosed pretraining/training data: no contamination-free
model holdout is established. See EVALUATION_DATASET.md for attribution and transformations.

Estimates remain uncalibrated. No probability-mode claim, UI risk threshold, fine-tuning
or automatic training is enabled. Preserve per-ID numeric results and source hashes;
review errors with representative, verified labels before optional Phase 7. Do not
interpret a below-cutoff score as evidence that an email is legitimate.
""")
    return "\n\n".join(section.strip() for section in sections) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Render saved non-content baseline results.")
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(render(json.loads(args.results.read_text())))


if __name__ == "__main__":
    main()
