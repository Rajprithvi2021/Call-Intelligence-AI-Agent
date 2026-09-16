"""Single start command for Railway: runs the API or the Streamlit UI.

The role comes from APP_ROLE ("api" or "ui"). If it is not set, a Railway service
whose name contains "ui" runs the UI; everything else runs the API.

    python scripts/start.py
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def role() -> str:
    explicit = os.getenv("APP_ROLE", "").strip().lower()
    if explicit in ("api", "ui"):
        return explicit
    service_words = re.split(r"[-_\s]+", os.getenv("RAILWAY_SERVICE_NAME", "").lower())
    return "ui" if "ui" in service_words else "api"


def main() -> None:
    os.chdir(ROOT)
    which = role()
    print(f"start.py: starting {which} (service={os.getenv('RAILWAY_SERVICE_NAME', '-')}, "
          f"port={os.getenv('PORT', 'default')})", flush=True)
    if which == "ui":
        script = ROOT / "scripts" / "run_ui.py"
        os.execv(sys.executable, [sys.executable, str(script)])
    os.execv(sys.executable, [sys.executable, "-m", "app.api"])


if __name__ == "__main__":
    main()
