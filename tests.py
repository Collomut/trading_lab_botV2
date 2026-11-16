#!/usr/bin/env python3
"""Root test runner. Delegates to pytest so `python tests.py` works without a venv."""
import sys

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(["tests/unit", "-q"]))