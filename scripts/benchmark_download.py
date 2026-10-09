"""Compare ZIP preparation costs using bounded samples of existing files."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile


def run_case(paths: list[str], sink: str, mode: str) -> dict:
    for name in paths:
        with open(name, "rb") as source:
            while source.read(1024 * 1024):
                pass
    compression = zipfile.ZIP_STORED if mode == "stored" else zipfile.ZIP_DEFLATED
    level = {"stored": None, "deflate1": 1, "deflate6": 6}[mode]
    with tempfile.TemporaryDirectory(prefix="download-zip-bench-") as directory:
        target = io.BytesIO() if sink == "memory" else Path(directory) / "sample.zip"
        started = time.perf_counter()
        cpu_started = time.process_time()
        with zipfile.ZipFile(target, "w", compression=compression, compresslevel=level) as archive:
            for index, name in enumerate(paths):
                archive.write(name, arcname=f"PDF/{index:03d}_{Path(name).name}")
        seconds = time.perf_counter() - started
        cpu_seconds = time.process_time() - cpu_started
        size = target.getbuffer().nbytes if sink == "memory" else target.stat().st_size
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak_rss_mib = rss / (1024**2 if sys.platform == "darwin" else 1024)
        except ImportError:
            peak_rss_mib = None
        if sink == "memory":
            target.seek(0)
        with zipfile.ZipFile(target) as archive:
            if len(archive.infolist()) != len(paths) or archive.testzip() is not None:
                raise RuntimeError("ZIP integrity check failed")
        if sink == "memory":
            target.close()
    return {"seconds": seconds, "cpu_seconds": cpu_seconds, "zip_bytes": size,
            "peak_rss_mib": peak_rss_mib, "crc_ok": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--status-json", type=Path, help="Existing batch status with summary.results[].pdf_path")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--max-mib", type=float, default=64)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-spec", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--sink", choices=("memory", "disk"), help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("stored", "deflate1", "deflate6"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_spec:
        print(json.dumps(run_case(json.loads(args.worker_spec.read_text()), args.sink, args.mode)))
        return
    if args.limit < 1 or args.max_mib <= 0 or args.repeats < 1:
        parser.error("limit, max-mib and repeats must be positive")
    candidates = list(args.files)
    if args.status_json:
        status = json.loads(args.status_json.read_text(encoding="utf-8"))
        candidates.extend(Path(row["pdf_path"]) for row in
                          (status.get("summary") or {}).get("results", []) if row.get("pdf_path"))
    paths: list[str] = []
    total = 0
    for path in candidates:
        if not path.is_file() or str(path) in paths:
            continue
        size = path.stat().st_size
        if total + size > args.max_mib * 1024**2:
            continue
        paths.append(str(path))
        total += size
        if len(paths) == args.limit:
            break
    if not paths:
        parser.error("No readable samples fit the byte limit")
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "file_count": len(paths), "input_bytes": total, "repeats": args.repeats,
              "notes": ["Sources are read before each timed run; results use warm OS/SMB caches.",
                        "Disk output uses the system temporary directory and does not fsync.",
                        "ZIP CRC verification occurs after timing; this does not measure HTTP throughput."],
              "cases": []}
    with tempfile.TemporaryDirectory(prefix="download-bench-spec-") as directory:
        spec = Path(directory) / "samples.json"
        spec.write_text(json.dumps(paths), encoding="utf-8")
        samples = {(sink, mode): [] for sink in ("memory", "disk")
                   for mode in ("stored", "deflate1", "deflate6")}
        for _ in range(args.repeats):
            for (sink, mode), runs in samples.items():
                command = [sys.executable, str(Path(__file__).resolve()), "--worker-spec", str(spec),
                           "--sink", sink, "--mode", mode]
                result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
                runs.append(json.loads(result.stdout))
        for (sink, mode), runs in samples.items():
            report["cases"].append({"sink": sink, "mode": mode,
                "median_seconds": statistics.median(r["seconds"] for r in runs),
                "median_cpu_seconds": statistics.median(r["cpu_seconds"] for r in runs),
                "zip_bytes": runs[0]["zip_bytes"],
                "saving_percent": 100 * (1 - runs[0]["zip_bytes"] / total),
                "runs": runs})
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
