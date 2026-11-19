# Exploratory evaluation dataset v1

Source: Arifa Islam Champa, Md Fazle Rabbi and Minhaz Fahim Zibran,
*Phishing Email Curated Datasets*, Zenodo v1 (2023),
[DOI 10.5281/zenodo.8339691](https://zenodo.org/records/8339691).
The source record declares CC-BY-4.0. Its historical corpora span 1995–2022.
Source SHA-256, published MD5, sizes and selected labels are pinned in
`bad_email_check.evaluation_dataset.SOURCES` and the generated manifest.

The public subset uses only Enron label 0 (non-spam as a proxy for legitimate)
and Nazario label 1 (source-labeled phishing). Enron's spam positives are excluded;
spam is not automatically scam. These are provider labels, not new human-reviewed
gold labels. Agreement on this subset is not a claim about modern Gmail accuracy.

```powershell
.\.venv\Scripts\python -m bad_email_check.evaluation_dataset --download
```

This explicit evaluation-only command downloads about 53 MB of public CSV data,
verifies pinned hashes, and builds ignored `data/evaluation/records/*.eml` plus
`manifest.json`. Newly downloaded raw files are removed after a successful build
unless `--keep-sources` is given. Pre-existing source files are preserved; mismatched
ones fail rather than being overwritten. Scans never invoke this command.

## Sampling and splits

No model predictions are used in selection. Eligible public bodies contain 80–1600
characters. Connected components group normalized complete templates, first-64-word
campaign proxies, available senders and normalized subject threads. Hashed group
slots assign train/validation/test before balanced hash-ranked sampling. Unknown
threads or campaigns cannot be guaranteed separated by these heuristics.

Each public class contributes 6 train, 6 validation and 12 test examples. Ten
separately marked authored safety fixtures are test-only: legitimate reset/billing/
security lookalikes, credential/payment deception, prompt injection, HTML displayed
link deception, missing headers and two long inputs. Synthetic cases are never
pooled with public examples to claim corpus accuracy. Train and validation are
reserved; baseline inference uses only the frozen test split.

The generated set has 58 records: 12 train, 12 validation and 34 test; test has
17 source/fixture labels of each class across 33 groups. One group contains two
test records, so uncertainty estimates must account for clustering. The manifest
contains IDs, labels, label-source/row references, group/split membership, relative
paths, sizes and hashes, never email bodies. The validator rejects content-hash
changes, path escapes and group/content duplicates across splits.

## Privacy and representation limits

No Gmail messages or user-retained feedback are used. Public text is processed by
the preparation program, never copied into agent reports/context. Addresses,
numeric runs and URL destinations are redacted; URLs map consistently to reserved
`.example` hosts. Public records use a neutral reserved sender and plaintext MIME
wrapper, retaining the redacted source subject/body. This changes their evidence
and removes important real-world identity signals. Redaction is not a guarantee
that every personal name or identifier has been removed. The local records remain
outside version control; reports retain only hashes, IDs and aggregate outcomes.

Authored fixtures use reserved names/destinations and are distinguished from real
public examples. They exercise safety behavior, not independently established
accuracy. No training, tuning, calibration, UI risk-band or release threshold is
authorized by this dataset task.

Historical verification refers to the original development workspace. Its run
archive, local data and checkpoints are not bundled. See [project history](PROJECT_HISTORY.md).
