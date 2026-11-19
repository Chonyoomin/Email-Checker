import json
import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4


class MetadataError(Exception):
    pass


class MetadataStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def initialize(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=1)) as connection, connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS scans (
                        scan_id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL,
                        score_kind TEXT NOT NULL,
                        retrieval_ms REAL NOT NULL,
                        extraction_ms REAL NOT NULL,
                        inference_ms REAL NOT NULL,
                        total_ms REAL NOT NULL,
                        checkpoint_revision TEXT,
                        parser_version TEXT NOT NULL,
                        question_set_version TEXT,
                        model_adapter_version TEXT,
                        calibration_version TEXT,
                        threshold_version TEXT,
                        is_test_double INTEGER NOT NULL
                    )
                """)
                for table in ("feedback", "reviewed_examples"):
                    connection.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table} (
                            feedback_id TEXT PRIMARY KEY,
                            scan_id TEXT NOT NULL REFERENCES scans(scan_id),
                            created_at TEXT NOT NULL,
                            label TEXT NOT NULL,
                            content_json TEXT
                        )
                    """)
                existing = {row[1] for row in connection.execute("PRAGMA table_info(scans)")}
                for name, kind in (
                    ("model_load_ms", "REAL"),
                    ("model_tensor_bytes", "INTEGER"),
                    ("process_rss_bytes", "INTEGER"),
                    ("process_peak_rss_bytes", "INTEGER"),
                    ("inference_phase", "TEXT"),
                ):
                    if name not in existing:
                        connection.execute(f"ALTER TABLE scans ADD COLUMN {name} {kind}")
                connection.execute("PRAGMA user_version = 3")
        except OSError, sqlite3.Error:
            raise MetadataError("Local metadata storage is unavailable.") from None

    def record(self, result, source):
        if source not in {"paste", "eml", "gmail"}:
            raise MetadataError("Invalid metadata source.")
        values = (
            result.scan_id,
            datetime.now(UTC).isoformat(),
            source,
            result.status,
            result.score_kind,
            result.timings.retrieval_ms,
            result.timings.extraction_ms,
            result.timings.inference_ms,
            result.timings.total_ms,
            result.checkpoint_revision,
            result.parser_version,
            result.question_set_version,
            result.model_adapter_version,
            result.calibration_version,
            result.threshold_version,
            int(result.is_test_double),
            result.runtime.model_load_ms,
            result.runtime.model_tensor_bytes,
            result.runtime.process_rss_bytes,
            result.runtime.process_peak_rss_bytes,
            result.runtime.inference_phase,
        )
        try:
            with (
                self.lock,
                closing(sqlite3.connect(self.path, timeout=1)) as connection,
                connection,
            ):
                connection.execute(
                    "INSERT INTO scans (scan_id,created_at,source,status,score_kind,"
                    "retrieval_ms,extraction_ms,inference_ms,total_ms,checkpoint_revision,"
                    "parser_version,question_set_version,model_adapter_version,calibration_version,"
                    "threshold_version,is_test_double,model_load_ms,model_tensor_bytes,"
                    "process_rss_bytes,process_peak_rss_bytes,inference_phase) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
        except sqlite3.Error:
            raise MetadataError("Could not save local scan metadata.") from None

    def feedback(self, data):
        content = None
        if data.retain_content:
            content = data.evidence.model_dump_json(
                exclude={"account_scope", "source_message_id", "fingerprint"}
            )
        feedback_id = str(uuid4())
        table = "reviewed_examples" if data.reviewed else "feedback"
        try:
            with (
                self.lock,
                closing(sqlite3.connect(self.path, timeout=1)) as connection,
                connection,
            ):
                connection.execute("PRAGMA foreign_keys = ON")
                if not connection.execute(
                    "SELECT 1 FROM scans WHERE scan_id = ?", (data.scan_id,)
                ).fetchone():
                    return None
                connection.execute(
                    f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)",
                    (feedback_id, data.scan_id, datetime.now(UTC).isoformat(), data.label, content),
                )
        except sqlite3.Error:
            raise MetadataError("Could not save feedback.") from None
        return {
            "feedback_id": feedback_id,
            "reviewed": data.reviewed,
            "content_retained": content is not None,
        }

    def export_feedback(self, after, limit, include_content=True):
        try:
            columns = (
                "*"
                if include_content
                else (
                    "feedback_id,scan_id,created_at,label,"
                    "content_json IS NOT NULL AS content_retained"
                )
            )
            with closing(sqlite3.connect(self.path, timeout=1)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    f"SELECT {columns}, 0 AS reviewed FROM feedback WHERE feedback_id > ? "
                    f"UNION ALL SELECT {columns}, 1 AS reviewed FROM reviewed_examples "
                    "WHERE feedback_id > ? "
                    "ORDER BY feedback_id LIMIT ?",
                    (after, after, limit + 1),
                ).fetchall()
            records = []
            for row in rows[:limit]:
                record = dict(row)
                if include_content:
                    content = record.pop("content_json")
                    record["evidence"] = json.loads(content) if content is not None else None
                else:
                    record["content_retained"] = bool(record["content_retained"])
                record["reviewed"] = bool(record["reviewed"])
                records.append(record)
            return {
                "records": records,
                "next_after": records[-1]["feedback_id"] if len(rows) > limit else None,
            }
        except sqlite3.Error, ValueError:
            raise MetadataError("Could not export feedback.") from None

    def delete_feedback(self, feedback_id):
        try:
            with (
                self.lock,
                closing(sqlite3.connect(self.path, timeout=1)) as connection,
                connection,
            ):
                connection.execute("PRAGMA secure_delete = ON")
                deleted = sum(
                    connection.execute(
                        f"DELETE FROM {table} WHERE feedback_id = ?", (feedback_id,)
                    ).rowcount
                    for table in ("feedback", "reviewed_examples")
                )
            return bool(deleted)
        except sqlite3.Error:
            raise MetadataError("Could not delete feedback.") from None
