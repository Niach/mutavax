"""Shared config for `backend/tests/validation/`.

Validation tests compare our pipeline's output against public ground truth.
They're slower and dataset-dependent; register a `validation` marker so they
can be opted into with `pytest -m validation` (and skipped from the default
fast suite)."""
from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "/tests/validation/" in str(item.fspath):
            item.add_marker(pytest.mark.validation)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "validation: public-dataset validation tests (see validation.md)",
    )
