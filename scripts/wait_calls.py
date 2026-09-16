"""Poll the API until no call is still processing. Usage: python scripts/wait_calls.py [api_url]"""
import json
import sys
import time
import urllib.request

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
deadline = time.time() + 900
while True:
    calls = json.load(urllib.request.urlopen(f"{API}/calls"))
    busy = [c for c in calls if c["status"] not in ("done", "failed")]
    if not busy or time.time() > deadline:
        break
    time.sleep(5)
for c in calls:
    print(c["id"], c["status"], c["title"], "|", c.get("tag"), "| open reviews:", c.get("open_reviews"),
          "|", (c.get("error") or "")[:80])
