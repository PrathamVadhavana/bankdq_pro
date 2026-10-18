# Local benchmark record

Measured in the project-generation environment using the bundled 1,000-row synthetic source CSV.

- Python: 3.13.5
- File size: 58270 bytes
- Rows scanned per run: 1000
- Duplicate IDs detected: 4
- Repeats: 5
- Median elapsed time: 0.001447 seconds
- Median scan throughput: 690856.79 rows/second

This is a local microbenchmark of CSV parsing and transaction-ID duplicate scanning only. It excludes API, database writes, authentication, and reconciliation. Re-run on your own computer before using any performance figure on your resume.
