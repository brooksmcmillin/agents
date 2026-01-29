"""Root conftest.py to configure pytest."""

import sys
from pathlib import Path

# Add project root to sys.path so 'shared' and 'agents' can be imported
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
