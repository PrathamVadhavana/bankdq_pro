"""Run reproducible microbenchmarks and labeled application evaluations.

Examples:
    python scripts\run_benchmark_suite.py --sizes 1000 10000 --repeats 3
    python scripts\run_benchmark_suite.py --include-api --output benchmark\results.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Allow the documented `python scripts\...` invocation to import the repository package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.datasets import quality_fixture, reconciliation_fixture, write_rows
from benchmark.metrics import classification_metrics


def parse_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def scan_duplicate_ids(rows: list[dict]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for row in rows:
        transaction_id = (row.get("transaction_id") or "").strip()
        if transaction_id and transaction_id in seen:
            duplicates += 1
        elif transaction_id:
            seen.add(transaction_id)
    return duplicates


def measured(operation, repeats: int) -> tuple[list[float], int]:
    elapsed: list[float] = []
    peak_bytes = 0
    for _ in range(repeats):
        tracemalloc.start()
        start = time.perf_counter()
        operation()
        elapsed.append(time.perf_counter() - start)
        _, peak = tracemalloc.get_traced_memory()
        peak_bytes = max(peak_bytes, peak)
        tracemalloc.stop()
    return elapsed, peak_bytes


def benchmark_file(path: Path, repeats: int) -> dict:
    parsed_rows = parse_rows(path)
    parse_times, parse_peak = measured(lambda: parse_rows(path), repeats)
    scan_times, scan_peak = measured(lambda: scan_duplicate_ids(parsed_rows), repeats)
    rows = len(parsed_rows)
    return {
        "dataset_rows": rows,
        "dataset_bytes": path.stat().st_size,
        "duplicate_ids": scan_duplicate_ids(parsed_rows),
        "csv_parse": {
            "median_seconds": statistics.median(parse_times),
            "median_rows_per_second": rows / statistics.median(parse_times),
            "peak_memory_bytes": parse_peak,
        },
        "duplicate_id_scan": {
            "median_seconds": statistics.median(scan_times),
            "median_rows_per_second": rows / statistics.median(scan_times),
            "peak_memory_bytes": scan_peak,
        },
        "repeats": repeats,
    }


def evaluate_api() -> dict:
    with tempfile.TemporaryDirectory(prefix="bankdq-eval-") as directory:
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(directory) / 'evaluation.db'}"
        from fastapi.testclient import TestClient
        from app.main import app

        source, expected_issues = quality_fixture()
        recon_source, recon_ledger, expected_recon = reconciliation_fixture()
        source_path = Path(directory) / "quality.csv"
        ledger_path = Path(directory) / "ledger.csv"
        write_rows(source_path, source)
        write_rows(ledger_path, recon_ledger)
        with TestClient(app) as client:
            username = f"benchmark_{uuid.uuid4().hex[:10]}"
            password = "benchmark-password"
            assert client.post("/auth/register", json={"username": username, "password": password}).status_code == 201
            token = client.post("/auth/login", json={"username": username, "password": password}).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            issue_response = client.post(
                "/batches",
                headers=headers,
                data={"name": "quality-evaluation", "chunk_size": "50"},
                files=[("files", ("quality.csv", source_path.read_bytes(), "text/csv"))],
            )
            issue_batch_id = issue_response.json()["batch_id"]
            issue_items = client.get(f"/batches/{issue_batch_id}/issues?page=1&page_size=100", headers=headers).json()["items"]
            actual_issues: dict[str, set[int]] = {}
            for item in issue_items:
                actual_issues.setdefault(item["code"], set()).add(item["row"])

            start = time.perf_counter()
            recon_response = client.post(
                "/batches",
                headers=headers,
                data={"name": "reconciliation-evaluation", "chunk_size": "50"},
                files=[
                    ("files", ("source.csv", write_temp(source_path, recon_source), "text/csv")),
                    ("ledger_file", ("ledger.csv", ledger_path.read_bytes(), "text/csv")),
                ],
            )
            elapsed = time.perf_counter() - start
            recon_batch_id = recon_response.json()["batch_id"]
            recon_items = client.get(f"/batches/{recon_batch_id}/reconciliation?page=1&page_size=100", headers=headers).json()["items"]

        issue_metrics = {
            code: classification_metrics(expected, actual_issues.get(code, set()))
            for code, expected in expected_issues.items()
        }
        actual_statuses = {item["transaction_id"]: item["status"] for item in recon_items}
        status_accuracy = sum(actual_statuses.get(key) == value for key, value in expected_recon.items()) / len(expected_recon)
        expected_discrepancies = {key for key, value in expected_recon.items() if value != "MATCHED"}
        actual_discrepancies = {key for key, value in actual_statuses.items() if value != "MATCHED"}
        return {
            "quality_detection": {
                "matching_rule": "Expected and detected issue row numbers must match within each issue code; duplicate groups count each repeated row after the first.",
                "per_issue_type": issue_metrics,
            },
            "reconciliation": {
                "expected_statuses": expected_recon,
                "actual_statuses": actual_statuses,
                "status_classification_accuracy": status_accuracy,
                "discrepancy_metrics": classification_metrics(expected_discrepancies, actual_discrepancies),
                "coverage": len(actual_statuses) / len(expected_recon),
            },
            "end_to_end_api": {
                "rows": len(recon_source),
                "elapsed_seconds": elapsed,
                "rows_per_second": len(recon_source) / elapsed,
                "database": "temporary SQLite",
            },
            "independent_database_persistence": {
                "status": "unavailable",
                "reason": "The current application persists records as part of batch processing; no separate persistence-only contract is exposed.",
            },
            "independent_reconciliation": {
                "status": "unavailable",
                "reason": "The current application performs reconciliation inside batch processing; no separate reconciliation-only contract is exposed.",
            },
        }


def write_temp(path: Path, rows: list[dict]) -> bytes:
    temporary = path.with_name("reconciliation-source.csv")
    write_rows(temporary, rows)
    return temporary.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 50000, 100000])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="benchmark/results.json")
    parser.add_argument("--csv-output", default="benchmark/results.csv")
    parser.add_argument("--include-api", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or any(size < 1 for size in args.sizes):
        raise SystemExit("sizes and repeats must be positive")

    with tempfile.TemporaryDirectory(prefix="bankdq-benchmark-") as directory:
        from scripts.generate_synthetic_data import generate
        benchmark_results = []
        for size in args.sizes:
            dataset_dir = Path(directory) / str(size)
            generate(dataset_dir, size, args.seed)
            benchmark_results.append(benchmark_file(dataset_dir / "source_transactions.csv", args.repeats))

    result = {
        "schema_version": 1,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "benchmarks": benchmark_results,
        "evaluation": evaluate_api() if args.include_api else {"status": "not_run", "command_option": "--include-api"},
        "limitations": [
            "Microbenchmarks measure CSV parsing and duplicate-ID scanning separately.",
            "End-to-end API timing includes request handling, persistence, and reconciliation; it is not comparable to microbenchmark throughput.",
            "Peak memory uses tracemalloc and excludes native allocations not tracked by Python.",
            "All data is deterministic synthetic data; results depend on hardware, Python, database, and configuration.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    csv_rows = []
    for item in benchmark_results:
        for stage in ("csv_parse", "duplicate_id_scan"):
            values = item[stage]
            csv_rows.append({
                "dataset_rows": item["dataset_rows"],
                "dataset_bytes": item["dataset_bytes"],
                "benchmark": stage,
                "median_seconds": values["median_seconds"],
                "median_rows_per_second": values["median_rows_per_second"],
                "peak_memory_bytes": values["peak_memory_bytes"],
                "repeats": item["repeats"],
                "seed": args.seed,
            })
    csv_output = Path(args.csv_output)
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    with csv_output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
