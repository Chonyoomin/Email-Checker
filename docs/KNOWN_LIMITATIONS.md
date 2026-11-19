# Known limitations

This is an experimental local prototype. An uncalibrated /100 model score is not a
probability or a legitimacy guarantee. Baseline phishing recall was poor and the
first specialization candidate failed its improvement gate. See
[historical evaluation](BASELINE_EVALUATION.md), [specialization](CALIBRATION_EVALUATION.md)
and [history](PROJECT_HISTORY.md) for measured limits.

- Complete canonical input and question overhead must fit 2,048 tokens; long or
  incomplete messages yield needs-review/no score rather than a partial assessment.
- Linked websites and attachments are not inspected. Imported authentication
  headers are claims, not independently verified sender authentication.
- CPU scans can take seconds to tens of seconds. The original warm p95 missed the
  3-second engineering target. Cache hits do not measure fresh inference speed.
- Gmail requires owner-configured read-only OAuth and the native protected token store.
  Google sign-in stays user-driven; optional Docker Gmail has additional unverified limits.
- Malicious feedback is stored only with consent, remains unverified and never
  automatically trains the model. Retained content and exported feedback need local care.
- The UI/model are intended for one local user on loopback, not public hosting.
- Windows/Python 3.14 and the Linux CPU container were exercised in development;
  a new machine still needs its own setup verification.

No private datasets, reviewed labels, trained candidate or model weights are bundled.
The optional training tools require newly supplied, verified and versioned data;
the removed development dataset cannot be silently recreated as owner-reviewed.
