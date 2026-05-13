"""Make the scripts/ directory importable for tests.

Dev environment last verified: pytest 9.0.3 on CPython 3.10.10.
Test files use only plain `def test_*` + `assert`, so older pytests
(back to roughly 3.x) should also work; bump the version here if you
adopt a feature that requires a newer floor.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
