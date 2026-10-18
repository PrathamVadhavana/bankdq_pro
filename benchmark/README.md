# Reproducible benchmark outputs

Run from the repository root:

```cmd
python scripts\run_benchmark_suite.py --repeats 5 --seed 42 --include-api
```

The command generates `benchmark/results.json` and `benchmark/results.csv`.
Those files are intentionally ignored by Git because measurements are
machine-specific and must be regenerated in the environment being reported.

The JSON separates CSV parsing, duplicate-ID scanning, and optional API
end-to-end processing. It also contains labeled data-quality and
reconciliation evaluation metrics. Use only observed values from a newly
generated result file in a resume or report.
