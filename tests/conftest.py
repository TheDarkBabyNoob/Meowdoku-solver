import os
import sys
from pathlib import Path

# Run Qt headlessly for tests (no real display needed) and keep persistence
# writes out of the developer's real Application Support directory.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MEOWDOKU_APP_SUPPORT_DIR", str(Path(__file__).parent / "_test_app_support"))

sys.path.insert(0, str(Path(__file__).parent.parent))
