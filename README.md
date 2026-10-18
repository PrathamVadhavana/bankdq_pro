# BankDQ Pro — Banking Data Quality, Batch Processing & Reconciliation

**Portfolio prototype, not production banking/compliance software.** Use synthetic data only.

## Why this project is relevant to financial services

BankDQ Pro demonstrates a common operational control problem: ingesting transaction extracts from multiple systems, finding data-quality defects, reconciling source records against a ledger, and retaining an audit trail of processing actions. It does not claim regulatory certification or production readiness.

## Features

- **Custom multi-file batch upload:** up to 20 source CSV files plus one optional reference/ledger CSV per batch.
- **Configurable chunk size:** choose 50–10,000 rows per processing chunk; records are flushed to the database per chunk.
- **Reference-based reconciliation:** matched, source-only, ledger-only, duplicate-reference, amount/account/date/currency mismatch statuses.
- **Data quality checks:** missing transaction ID, malformed amount/date, repeated transaction ID, and possible duplicate business key (`account_id + transaction_date + amount + currency`).
- **Authentication and tenant isolation:** account registration, PBKDF2 password hashing, signed bearer tokens, owner-scoped batch/issue/reconciliation/audit queries.
- **Financial-exposure prioritization:** quantifies amount-mismatch deltas and source-only/ledger-only amounts so reviewers can prioritize reconciliation breaks. Mixed currencies must not be summed as if they were one currency.
- **Operational visibility:** structured JSON logs, per-batch metrics, audit trail, paginated issue and reconciliation endpoints, CSV export.
- **Database migration scaffold:** Alembic configuration and initial schema revision.
- **Engineering workflow:** pytest tests, Ruff lint in GitHub Actions, Docker and Docker Compose for PostgreSQL.
- **Repeatable benchmark script:** reports actual local CSV parse/duplicate-scan throughput to `benchmark/results.json`.

## CSV schema

Required columns: `transaction_id`, `amount`. Recommended columns: `account_id`, `transaction_date` (ISO `YYYY-MM-DD`), `currency`, `description`. Header capitalization and spaces are normalized. Both source and ledger files use the same schema.

## Windows setup (Command Prompt)

```cmd
cd E:\Fintech Projects\bankdq_pro
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
copy .env.example .env
python scripts\generate_synthetic_data.py --rows 1000 --out sample_data\generated
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`. Register via `/auth/register`, log in at `/auth/login`, then click **Authorize** and enter `Bearer <access_token>` (or use the Streamlit dashboard).

In a second terminal, from the same project directory:

```cmd
.venv\Scripts\activate.bat
python -m streamlit run dashboard\app.py
```

Dashboard URL: `http://localhost:8501`.

## Use batch upload in Swagger

1. Register and login; copy `access_token` from `/auth/login`.
2. Click **Authorize** and paste `Bearer YOUR_TOKEN`.
3. Expand `POST /batches`.
4. Add one or more `files`, choose `name`, set `chunk_size` (50–10000), and optionally attach `ledger_file`.
5. Inspect `/batches/{batch_id}/issues`, `/reconciliation`, `/metrics`, and `/audit`.

## Migrations

For a fresh local database, the app creates tables for convenience. To use migrations deliberately:

```cmd
alembic upgrade head
```

For subsequent schema changes, create a migration with `alembic revision --autogenerate -m "describe change"` and review it before applying. In a production deployment, disable startup `create_all` and use migrations as a controlled deployment step.

## Benchmark

```cmd
python scripts\generate_synthetic_data.py --rows 10000 --out sample_data\generated
python scripts\run_benchmark.py --source sample_data\generated\source_transactions.csv --repeats 5
```

This benchmark measures local CSV parsing plus transaction-ID duplicate scanning only. It is **not** end-to-end upload, database, or reconciliation throughput. Save the generated `benchmark/results.json` with the environment and date when reporting results. Results vary by hardware and Python version; never copy benchmark values from another machine.

## Tests and lint

```cmd
pytest -q
ruff check app tests scripts dashboard
```

## API endpoints

- `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- `POST /batches` — multiple source files, optional `ledger_file`, custom `chunk_size`
- `GET /batches`, `GET /batches/{id}`, `GET /batches/{id}/metrics`
- `GET /batches/{id}/issues?page=1&page_size=50`
- `GET /batches/{id}/reconciliation?page=1&page_size=50`
- `GET /batches/{id}/reconciliation.csv`
- `GET /audit?page=1&page_size=50`
- `GET /health`

## Important limitations and security notes

- Prototype only: not PCI DSS, SOC 1/2, RBI, or other regulatory-compliance certified.
- The included token implementation is intended for learning; use a vetted identity provider or reviewed JWT/OAuth library for a real deployment.
- Add rate limiting, HTTPS, secret management, retention controls, malware scanning, file streaming, and security review before any production use.
- Chunk size controls processing chunking, not parallelism. The CSV file is currently read into memory before row-level chunking; for very large files, switch to a streaming parser.
- Business-key duplicate detection is heuristic and may flag legitimate repeated transactions. It is a warning, not a definitive fraud finding.
- Reconciliation uses transaction ID as the primary reference and compares amount, account, date, and currency. It is not a complete double-entry ledger control.
- Synthetic records only; do not upload real banking/customer data.
