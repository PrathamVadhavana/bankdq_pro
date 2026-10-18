"""Repeatable local benchmark using the bundled synthetic CSV files.
Measures CSV parsing + deterministic ID-index construction, not end-to-end API/DB throughput.
Run: python scripts/generate_synthetic_data.py --rows 10000 --out sample_data/generated
     python scripts/run_benchmark.py --source sample_data/generated/source_transactions.csv --repeats 5
"""
import argparse, csv, json, platform, statistics, time
from pathlib import Path
from datetime import datetime, timezone

def run_once(path):
    start=time.perf_counter()
    seen=set(); rows=0; duplicate_ids=0
    with open(path,newline="",encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows+=1
            txid=(row.get("transaction_id") or "").strip()
            if txid in seen: duplicate_ids+=1
            elif txid: seen.add(txid)
    elapsed=time.perf_counter()-start
    return {"rows":rows,"duplicate_ids":duplicate_ids,"elapsed_seconds":elapsed,
            "rows_per_second":round(rows/elapsed,2) if elapsed else None}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",default="sample_data/sample_transactions.csv")
    p.add_argument("--repeats",type=int,default=5)
    p.add_argument("--output",default="benchmark/results.json")
    a=p.parse_args(); path=Path(a.source)
    if not path.exists(): raise SystemExit(f"CSV not found: {path}")
    runs=[run_once(path) for _ in range(max(1,a.repeats))]
    result={"benchmark":"CSV parse + transaction-ID duplicate scan","measured_at_utc":datetime.now(timezone.utc).isoformat(),
      "python":platform.python_version(),"platform":platform.platform(),"file":str(path),"file_bytes":path.stat().st_size,
      "repeats":len(runs),"rows":runs[0]["rows"],"duplicate_ids":runs[0]["duplicate_ids"],
      "median_seconds":round(statistics.median(x["elapsed_seconds"] for x in runs),6),
      "median_rows_per_second":round(statistics.median(x["rows_per_second"] for x in runs),2),"runs":runs,
      "limitations":"Local single-process CSV parsing microbenchmark; excludes API, database writes, network, auth, and reconciliation."}
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
if __name__=="__main__": main()
