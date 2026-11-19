# Local scan metadata

The app creates `data/metadata.sqlite3` by default. Set
`EMAIL_CHECK_METADATA_DB_PATH` to relocate it. The path's parent must be writable;
initialization or write errors fail explicitly instead of silently losing records.

Each returned scan result stores a random scan ID, UTC creation time, input type,
status, score kind, four timings, model/parser/question/calibration/threshold
versions and the test-double flag. The store uses an explicit column allowlist.
It does not save the email body, subject, sender, filename, links, authentication
headers, account scope, message ID, fingerprint, warnings or model assessment.
HTTP validation and other errors without a ScanResult are not scan-history rows.

SQLite files are ignored by Git. Protect the data directory with local user
permissions. Scans and model inference remain local; this store does not send data
or train a model. [Feedback retention](FEEDBACK.md) uses separate tables and
requires explicit opt-in; it does not change the scan metadata allowlist.
