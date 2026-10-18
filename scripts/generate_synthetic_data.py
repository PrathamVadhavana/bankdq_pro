import csv, random, argparse
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal

def generate(out_dir: Path, rows: int, seed: int = 42):
    random.seed(seed); out_dir.mkdir(parents=True,exist_ok=True)
    source_path=out_dir/"source_transactions.csv"; ledger_path=out_dir/"ledger_transactions.csv"
    fields=["transaction_id","account_id","transaction_date","amount","currency","description"]
    source=[]; ledger=[]
    start=date(2026,1,1)
    for i in range(1,rows+1):
        amount=Decimal(random.randrange(100,500000))/100
        day=(start+timedelta(days=random.randrange(0,270))).isoformat()
        row={"transaction_id":f"TX{i:08d}","account_id":f"AC{random.randrange(1,max(10,rows//3)):07d}",
             "transaction_date":day,"amount":f"{amount:.2f}","currency":"INR",
             "description":random.choice(["UPI transfer","NEFT credit","POS purchase","IMPS transfer","ATM withdrawal"])}
        source.append(row); ledger.append(dict(row))
    # Seed deterministic reconciliation exceptions and data quality issues.
    for idx in range(9, len(source), 100):
        ledger[idx]["amount"]=f"{Decimal(ledger[idx]['amount']) + Decimal('1.25'):.2f}"
    for idx in range(19, len(source), 200):
        ledger[idx]["account_id"]="AC-MISMATCH"
    for idx in range(29, len(source), 250):
        source[idx]["transaction_id"]=source[idx-1]["transaction_id"]
    for idx in range(39, len(source), 300):
        source[idx]["amount"]="not-a-number"
    for idx in range(49, len(source), 400):
        ledger[idx]["transaction_id"]="LEDGER-ONLY-"+str(idx)
    for path, data in ((source_path,source),(ledger_path,ledger)):
        with path.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(data)
    print(f"Wrote {len(source)} source rows to {source_path}")
    print(f"Wrote {len(ledger)} ledger rows to {ledger_path}")
    print("Synthetic data only; intentionally includes amount/account mismatches, duplicate IDs, invalid amounts and ledger-only IDs.")

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--rows",type=int,default=1000); p.add_argument("--out",default="sample_data/generated"); p.add_argument("--seed",type=int,default=42)
    a=p.parse_args(); generate(Path(a.out),a.rows,a.seed)
