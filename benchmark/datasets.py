from __future__ import annotations

import csv
from pathlib import Path

FIELDS = [
    "transaction_id",
    "account_id",
    "transaction_date",
    "amount",
    "currency",
    "description",
]


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def quality_fixture() -> tuple[list[dict], dict[str, set[int]]]:
    rows = [
        {"transaction_id": "Q1", "account_id": "A1", "transaction_date": "2026-01-01", "amount": "10.00", "currency": "INR", "description": "valid"},
        {"transaction_id": "Q1", "account_id": "A2", "transaction_date": "2026-01-02", "amount": "20.00", "currency": "INR", "description": "duplicate id"},
        {"transaction_id": "Q3", "account_id": "A3", "transaction_date": "2026-01-03", "amount": "not-a-number", "currency": "INR", "description": "invalid amount"},
        {"transaction_id": "", "account_id": "A4", "transaction_date": "2026-01-04", "amount": "40.00", "currency": "INR", "description": "missing id"},
        {"transaction_id": "Q5", "account_id": "", "transaction_date": "2026-01-05", "amount": "50.00", "currency": "INR", "description": "missing account"},
        {"transaction_id": "Q6", "account_id": "A6", "transaction_date": "not-a-date", "amount": "60.00", "currency": "INR", "description": "invalid date"},
    ]
    expected = {
        "DUPLICATE_TRANSACTION_ID": {3},
        "INVALID_AMOUNT": {4},
        "MISSING_TRANSACTION_ID": {5},
        "MISSING_ACCOUNT_ID": {6},
        "INVALID_DATE": {7},
    }
    return rows, expected


def reconciliation_fixture() -> tuple[list[dict], list[dict], dict[str, str]]:
    def row(txid: str, account: str, date: str, amount: str, currency: str = "INR") -> dict:
        return {
            "transaction_id": txid,
            "account_id": account,
            "transaction_date": date,
            "amount": amount,
            "currency": currency,
            "description": "evaluation",
        }

    source = [
        row("R_MATCH", "A1", "2026-01-01", "10.00"),
        row("R_AMOUNT", "A2", "2026-01-02", "20.00"),
        row("R_ACCOUNT", "A3", "2026-01-03", "30.00"),
        row("R_DATE", "A4", "2026-01-04", "40.00"),
        row("R_CURRENCY", "A5", "2026-01-05", "50.00", "INR"),
        row("R_SOURCE_ONLY", "A6", "2026-01-06", "60.00"),
        row("R_DUP", "A7", "2026-01-07", "70.00"),
        row("R_DUP", "A7", "2026-01-07", "70.00"),
    ]
    ledger = [
        row("R_MATCH", "A1", "2026-01-01", "10.00"),
        row("R_AMOUNT", "A2", "2026-01-02", "21.00"),
        row("R_ACCOUNT", "WRONG", "2026-01-03", "30.00"),
        row("R_DATE", "A4", "2026-02-04", "40.00"),
        row("R_CURRENCY", "A5", "2026-01-05", "50.00", "USD"),
        row("R_LEDGER_ONLY", "A8", "2026-01-08", "80.00"),
        row("R_DUP", "A7", "2026-01-07", "70.00"),
        row("R_DUP", "A7", "2026-01-07", "70.00"),
    ]
    expected = {
        "R_MATCH": "MATCHED",
        "R_AMOUNT": "AMOUNT_MISMATCH",
        "R_ACCOUNT": "ACCOUNT_MISMATCH",
        "R_DATE": "DATE_MISMATCH",
        "R_CURRENCY": "CURRENCY_MISMATCH",
        "R_SOURCE_ONLY": "SOURCE_ONLY",
        "R_LEDGER_ONLY": "LEDGER_ONLY",
        "R_DUP": "DUPLICATE_REFERENCE",
    }
    return source, ledger, expected
