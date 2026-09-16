"""Start the Streamlit UI on $PORT (Railway) without relying on shell variable expansion.

    python scripts/run_ui.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

os.chdir(ROOT)
os.execv(sys.executable, [
    sys.executable, "-m", "streamlit", "run", str(ROOT / "ui" / "streamlit_app.py"),
    "--server.port", os.getenv("PORT", "8501"),
    "--server.address", os.getenv("HOST", "0.0.0.0"),
    "--server.headless", "true",
    "--browser.gatherUsageStats", "false",
])
