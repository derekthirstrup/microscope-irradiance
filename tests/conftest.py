from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


@pytest.fixture
def argo_path():
    return EXAMPLES / "argopower_example.csv"


@pytest.fixture
def manual_path():
    return EXAMPLES / "manual_example_filled.csv"
