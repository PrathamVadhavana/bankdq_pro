Generate source and ledger CSVs with deterministic synthetic exceptions:

    python scripts/generate_synthetic_data.py --rows 1000 --out sample_data/generated --seed 42

Upload `source_transactions.csv` as one source file and `ledger_transactions.csv` as the optional ledger file.
Never use real customer, cardholder, account, or transaction data in this portfolio demo.
