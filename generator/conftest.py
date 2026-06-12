from __future__ import annotations

"""
conftest.py — adds the generator directory to sys.path so that all modules
(config, vocab, payload, etc.) are importable in tests without relative imports.
"""

import sys
from pathlib import Path

# Insert generator/ at the front of sys.path once for the whole test session.
# This allows `import config`, `import vocab` etc. from any test file.
_GENERATOR_DIR = Path(__file__).parent
if str(_GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_GENERATOR_DIR))
