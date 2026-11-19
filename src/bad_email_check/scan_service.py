import asyncio
import hashlib
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .config import Settings
from .contracts import ModelAssessment, Readiness, RuntimeMetrics, Timings
from .laya_adapter import CoverageError
from .model_adapter import ModelAdapter, TestDoubleAdapter
from .presentation import present_assessment
from .questions import evidence_state
from .runtime_metrics import process_memory


class ScanError(Exception):
    def __init__(self, code: str, message: str, status: int = 503, retryable: bool = False):
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class CacheVersions:
    preprocessing: str = "state-v1"
    calibration: str = "none"
    thresholds: str = "none"


class ScanService:
    def __init__(self, settings: Settings, adapter: ModelAdapter | None = None):
        if (
            adapter is not None
            and adapter.identity.is_test_double
            and settings.mode == "production"
        ):
            raise ValueError("Production cannot use a test double")
        self.settings = settings
        self.adapter = adapter
        self.model_load_ms = None
        self.inference_runs = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="email-inference")
        self.slots = threading.BoundedSemaphore(settings.queue_size + 1)
        self.cache = OrderedDict()
        self.cache_lock = threading.Lock()
        self.cache_epoch = 0
        self.cache_versions = CacheVersions()
        self.setup_code = "checkpoint_missing"
        self.closed = False

    async def start(self):
        if self.adapter is not None:
            return
        if self.settings.model_backend == "test_double":
            self.adapter = TestDoubleAdapter(self.settings)
            return
        if self.settings.checkpoint_path is None:
            return
        self.setup_code = "checkpoint_unavailable"
        load_started = time.monotonic()
        try:
            from .laya_adapter import LayaAdapter

            self.adapter = await asyncio.get_running_loop().run_in_executor(
                self.executor, LayaAdapter, self.settings.checkpoint_path
            )
        except Exception:
            self.adapter = None
        finally:
            self.model_load_ms = (time.monotonic() - load_started) * 1000

    def readiness(self) -> Readiness:
        if self.adapter is None:
            return Readiness(
                code=self.setup_code,
                mode=self.settings.mode,
                message="Configure a complete local LAYA checkpoint and inference dependencies.",
            )
        fake = self.adapter.identity.is_test_double
        return Readiness(
            code="test_double" if fake else "ready",
            mode=self.settings.mode,
            status="ready",
            model_loaded=not fake,
            is_test_double=fake,
            scans_available=True,
            message=(
                "TEST DOUBLE: simulated output only; no real model is loaded."
                if fake
                else "Local LAYA checkpoint loaded. Imported scans run offline."
            ),
        )

    def cache_key(self, evidence):
        identity = self.adapter.identity
        return (
            evidence.source,
            evidence.account_scope,
            evidence.fingerprint,
            hashlib.sha256(evidence_state(evidence).encode()).hexdigest(),
            identity.checkpoint_revision,
            identity.adapter_version,
            identity.question_set_version,
            evidence.parser_version,
            self.cache_versions.preprocessing,
            self.cache_versions.calibration,
            self.cache_versions.thresholds,
        )

    def clear_cache(self):
        with self.cache_lock:
            self.cache_epoch += 1
            self.cache.clear()

    def close(self):
        self.closed = True
        self.clear_cache()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def result(self, evidence, assessment, started, extraction_ms, inference_ms, phase="not_run"):
        result = present_assessment(
            evidence,
            assessment,
            Timings(
                extraction_ms=extraction_ms,
                inference_ms=inference_ms,
                total_ms=(time.monotonic() - started) * 1000,
            ),
            is_test_double=self.adapter.identity.is_test_double if self.adapter else False,
        )
        rss, peak = process_memory()
        result.runtime = RuntimeMetrics(
            model_load_ms=self.model_load_ms,
            model_tensor_bytes=getattr(self.adapter, "model_tensor_bytes", None),
            process_rss_bytes=rss,
            process_peak_rss_bytes=peak,
            inference_phase=phase,
        )
        return result

    def work(self, evidence, started, extraction_ms, cache_epoch):
        if time.monotonic() - started >= self.settings.scan_deadline_seconds:
            raise ScanError("scan_timeout", "The scan deadline expired.", 504, True)
        if (
            evidence.extraction_status != "complete"
            or evidence.truncated
            or evidence.context_limit_exceeded
        ):
            return self.result(evidence, None, started, extraction_ms, 0.0)
        key = self.cache_key(evidence)
        with self.cache_lock:
            cached = self.cache.get(key) if cache_epoch == self.cache_epoch else None
            if cached is not None:
                self.cache.move_to_end(key)
        if cached is not None:
            return self.result(
                evidence,
                ModelAssessment.model_validate(cached),
                started,
                extraction_ms,
                0.0,
                "cached",
            )
        inference_start = time.monotonic()
        prior_runs = self.inference_runs
        phase = "first" if prior_runs == 0 else "warm"
        try:
            assessment = self.adapter.assess(evidence)
            assessment = ModelAssessment.model_validate(assessment.model_dump())
            identity = self.adapter.identity
            if (
                assessment.checkpoint_revision,
                assessment.model_adapter_version,
                assessment.question_set_version,
            ) != (
                identity.checkpoint_revision,
                identity.adapter_version,
                identity.question_set_version,
            ):
                raise ValueError("Assessment provenance differs from the loaded adapter")
        except CoverageError:
            evidence = evidence.model_copy(deep=True)
            evidence.warnings = (
                evidence.warnings
                + ["Complete model input exceeds supported context or was truncated."]
            )[-100:]
            return self.result(
                evidence,
                None,
                started,
                extraction_ms,
                (time.monotonic() - inference_start) * 1000,
                phase
                if getattr(self.adapter, "assess_calls", prior_runs + 1) > prior_runs
                else "not_run",
            )
        except Exception:
            raise ScanError(
                "model_failed", "Local inference failed or returned invalid output.", 502
            ) from None
        finally:
            self.inference_runs = getattr(self.adapter, "assess_calls", prior_runs + 1)
        if time.monotonic() - started >= self.settings.scan_deadline_seconds:
            raise ScanError("scan_timeout", "The scan deadline expired.", 504, True)
        if assessment.input_complete and assessment.input_coverage == 1.0 and not self.closed:
            with self.cache_lock:
                if (
                    self.settings.cache_entries
                    and cache_epoch == self.cache_epoch
                    and not self.closed
                ):
                    self.cache[key] = assessment.model_dump()
                    self.cache.move_to_end(key)
                    while len(self.cache) > self.settings.cache_entries:
                        self.cache.popitem(last=False)
        return self.result(
            evidence,
            assessment,
            started,
            extraction_ms,
            (time.monotonic() - inference_start) * 1000,
            phase,
        )

    async def scan(self, evidence, started: float, extraction_ms: float, cache_epoch=None):
        if self.closed or self.adapter is None:
            raise ScanError("model_not_ready", "The local model is not ready. Check setup.")
        if not self.slots.acquire(blocking=False):
            raise ScanError("scan_busy", "The scan queue is full. Try again shortly.", 429, True)
        try:
            with self.cache_lock:
                if cache_epoch is None:
                    cache_epoch = self.cache_epoch
            future = self.executor.submit(self.work, evidence, started, extraction_ms, cache_epoch)
        except Exception:
            self.slots.release()
            raise ScanError("model_not_ready", "The local model is not ready.") from None
        future.add_done_callback(lambda _: self.slots.release())
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(
            lambda value: value.exception() if not value.cancelled() else None
        )
        remaining = self.settings.scan_deadline_seconds - (time.monotonic() - started)
        done, _ = await asyncio.wait({wrapped}, timeout=max(0, remaining))
        if not done:
            raise ScanError("scan_timeout", "The scan deadline expired.", 504, True)
        return wrapped.result()
