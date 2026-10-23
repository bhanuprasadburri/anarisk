from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import sklearn

from common import split_name


def predict_loaded(artifact_path: Path, raw_url: str) -> float:
    """Call the existing cached backend predictor after its artifact has been loaded."""
    from app.services.url_model import predict_url

    result = predict_url(raw_url, artifact_path)
    if result.get("status") != "scored" or result.get("score") is None:
        raise RuntimeError(f"Existing URL prediction path failed: {result.get('status')}")
    return float(result["score"])


def process_memory_mb() -> dict:
    """Return current and peak memory for this process only, or explicit unsupported values."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        ok = psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        if not ok:
            return {"method": "Windows GetProcessMemoryInfo", "current_working_set_mb": None, "peak_working_set_mb": None,
                    "error": f"GetProcessMemoryInfo failed: {ctypes.get_last_error()}"}
        return {"method": "Windows GetProcessMemoryInfo (process working set)",
                "current_working_set_mb": round(counters.WorkingSetSize / 1048576, 2),
                "peak_working_set_mb": round(counters.PeakWorkingSetSize / 1048576, 2)}
    if sys.platform.startswith("linux"):
        try:
            pages = int(Path("/proc/self/statm").read_text().split()[1])
            page_size = os.sysconf("SC_PAGE_SIZE")
            current = pages * page_size / 1048576
        except (OSError, ValueError, IndexError, AttributeError):
            current = None
        try:
            import resource
            peak_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak = peak_raw / 1024  # Linux reports KiB.
        except (ImportError, AttributeError):
            peak = None
        return {"method": "Linux /proc/self/statm current RSS and resource.getrusage peak RSS (MiB)",
                "current_working_set_mb": round(current, 2) if current is not None else None,
                "peak_working_set_mb": round(peak, 2) if peak is not None else None}
    return {"method": "unsupported on this platform", "current_working_set_mb": None,
            "peak_working_set_mb": None, "error": f"No supported process-level memory API configured for {sys.platform}"}


def _worker(artifact: Path) -> int:
    from app.services.url_model import _load_artifact

    request = json.loads(sys.stdin.read())
    urls = request["urls"]
    if not urls:
        raise ValueError("Benchmark requires at least one prepared URL")
    # The marker lets the parent isolate interpreter/import/input initialization from model load.
    print(json.dumps({"worker_ready_before_model_load": True}), flush=True)
    baseline = process_memory_mb()
    stat = artifact.stat()
    load_started = time.perf_counter()
    _load_artifact(str(artifact.resolve()), stat.st_mtime_ns, stat.st_size)
    model_load_seconds = time.perf_counter() - load_started
    loaded = process_memory_mb()

    first_started = time.perf_counter()
    predict_loaded(artifact, urls[0])
    first_prediction_seconds = time.perf_counter() - first_started
    warmup_count = min(5, len(urls))
    for i in range(warmup_count):
        predict_loaded(artifact, urls[i])
    timings = []
    for value in urls:
        started = time.perf_counter()
        predict_loaded(artifact, value)
        timings.append(time.perf_counter() - started)
    memory = process_memory_mb()
    result = {
        "python": platform.python_version(), "os": platform.platform(), "machine": platform.machine(),
        "processor": platform.processor(), "numpy": np.__version__, "scikit_learn": sklearn.__version__,
        "artifact_bytes": artifact.stat().st_size,
        "model_load_seconds": model_load_seconds,
        "first_single_url_prediction_seconds": first_prediction_seconds,
        "warm_single_url_latency_seconds": {
            "sample_count": len(timings), "warmup_count": warmup_count,
            "minimum": float(np.min(timings)), "median": float(np.median(timings)),
            "p95": float(np.quantile(timings, .95)), "p99": float(np.quantile(timings, .99)),
            "maximum": float(np.max(timings)),
        },
        "memory": {"baseline_before_model_load": baseline, "after_model_load": loaded,
                   "after_warm_inference_peak": memory},
        "timing_scope": "Predictions call the existing backend predict_url path with its lru-cached artifact already loaded, so each includes file stat/cache lookup, shared URL normalization, TF-IDF transform, and one-row predict_proba; excludes dataset reading, JSON/report generation, and uncached artifact loading per prediction. This is an offline process benchmark, not web-service latency.",
    }
    print(json.dumps(result), flush=True)
    return 0


def _sample_test_urls(prepared: Path, count: int) -> list[str]:
    candidates = []
    with prepared.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"url", "label", "domain_group_hash"}.issubset(reader.fieldnames):
            raise ValueError("Prepared data must contain url,label,domain_group_hash")
        for row in reader:
            if row["label"] in {"0", "1"} and split_name(row["domain_group_hash"]) == "test":
                candidates.append(row["url"])
    if not candidates:
        raise ValueError("Prepared data has no test URLs")
    if len(candidates) <= count:
        return candidates
    indexes = np.linspace(0, len(candidates) - 1, num=count, dtype=int)
    return [candidates[i] for i in indexes]


def benchmark(prepared: Path, artifact: Path, output: Path, *, sample_count: int = 500) -> dict:
    urls = _sample_test_urls(prepared, sample_count)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(artifact.resolve())]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8")
    launch_started = time.perf_counter()
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps({"urls": urls}))
    process.stdin.close()
    marker = process.stdout.readline()
    launch_to_worker_ready = time.perf_counter() - launch_started
    if not marker or not json.loads(marker).get("worker_ready_before_model_load"):
        stderr = process.stderr.read() if process.stderr else ""
        process.wait()
        raise RuntimeError(f"Fresh benchmark worker failed before model load: {stderr[-1000:]}")
    payload = process.stdout.readline()
    remaining = process.stdout.read()
    stderr = process.stderr.read() if process.stderr else ""
    exit_code = process.wait()
    if exit_code != 0 or not payload:
        raise RuntimeError(f"Fresh benchmark worker failed with exit code {exit_code}: {stderr[-1000:]} {remaining[-1000:]}")
    measurements = json.loads(payload)
    result = {
        "benchmark_type": "offline fresh-process single-URL inference and process memory; descriptive only",
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "prepared_dataset_sha256": __import__("analyze_errors").sha256_file(prepared.resolve()),
        "artifact_sha256": __import__("analyze_errors").sha256_file(artifact.resolve()),
        "cold_process_startup_to_worker_ready_seconds": launch_to_worker_ready,
        "worker_exit_code": exit_code,
        **measurements,
        "sample_source": "deterministic evenly spaced URLs from the existing consumed test partition; values are never printed or saved",
        "sample_count": len(urls),
        "limitations": ["This is offline process timing, not API, network, or production latency.",
                        "The first prediction is measured after model load; warm samples include normalization and one-row feature transformation/prediction.",
                        "Fresh-process memory is process-local. Baseline is after Python imports and sample input parsing, before loading the artifact.",
                        "The consumed test partition is used only as a representative timing input, not for model selection."],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    warm = result["warm_single_url_latency_seconds"]
    memory = result["memory"]
    markdown = [
        "# Offline single-URL inference and memory benchmark", "",
        "These are local process measurements, not web-service or production latency.", "",
        f"- Prepared data SHA-256: `{result['prepared_dataset_sha256']}`",
        f"- Model SHA-256: `{result['artifact_sha256']}`",
        f"- Cold process startup to worker ready: {result['cold_process_startup_to_worker_ready_seconds']:.6f} s",
        f"- Model load: {result['model_load_seconds']:.6f} s",
        f"- First prediction after load: {result['first_single_url_prediction_seconds']:.6f} s",
        f"- Warm predictions: n={warm['sample_count']}, warmup={warm['warmup_count']}; min={warm['minimum']:.6f} s, median={warm['median']:.6f} s, p95={warm['p95']:.6f} s, p99={warm['p99']:.6f} s, max={warm['maximum']:.6f} s",
        f"- Memory method: {memory['after_warm_inference_peak']['method']}",
        f"- Baseline before model load: {memory['baseline_before_model_load']['current_working_set_mb']} MiB",
        f"- After model load: {memory['after_model_load']['current_working_set_mb']} MiB",
        f"- Peak after inference: {memory['after_warm_inference_peak']['peak_working_set_mb']} MiB", "",
        result["timing_scope"], "",
        "Input values were sampled from the consumed test partition for timing only; they were never written to this report."
    ]
    output.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark local one-URL model inference and fresh-process memory")
    parser.add_argument("prepared", nargs="?", type=Path)
    parser.add_argument("artifact", nargs="?", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sample-count", type=int, default=500)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return _worker(args.worker)
    if not args.prepared or not args.artifact or not args.output or args.sample_count < 1:
        parser.error("prepared, artifact, --output, and a positive --sample-count are required")
    result = benchmark(args.prepared, args.artifact, args.output, sample_count=args.sample_count)
    print(json.dumps({"output": str(args.output.resolve()),
                      "cold_process_startup_to_worker_ready_seconds": result["cold_process_startup_to_worker_ready_seconds"],
                      "model_load_seconds": result["model_load_seconds"],
                      "first_single_url_prediction_seconds": result["first_single_url_prediction_seconds"],
                      "warm_single_url_latency_seconds": result["warm_single_url_latency_seconds"],
                      "memory": result["memory"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
