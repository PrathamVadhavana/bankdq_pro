from benchmark.datasets import quality_fixture, reconciliation_fixture
from benchmark.metrics import classification_metrics


def test_quality_fixture_ground_truth_is_deterministic():
    rows_a, labels_a = quality_fixture()
    rows_b, labels_b = quality_fixture()
    assert rows_a == rows_b
    assert labels_a == labels_b
    assert labels_a["DUPLICATE_TRANSACTION_ID"] == {3}
    assert labels_a["INVALID_AMOUNT"] == {4}


def test_reconciliation_fixture_covers_supported_statuses():
    source, ledger, expected = reconciliation_fixture()
    assert len(source) == 8
    assert len(ledger) == 8
    assert set(expected.values()) == {
        "MATCHED",
        "AMOUNT_MISMATCH",
        "ACCOUNT_MISMATCH",
        "DATE_MISMATCH",
        "CURRENCY_MISMATCH",
        "SOURCE_ONLY",
        "LEDGER_ONLY",
        "DUPLICATE_REFERENCE",
    }


def test_classification_metrics_handle_duplicate_group_rows_without_accuracy_claims():
    metrics = classification_metrics({2, 3}, {2, 4})
    assert metrics["true_positive"] == 1
    assert metrics["false_positive"] == 1
    assert metrics["false_negative"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5
