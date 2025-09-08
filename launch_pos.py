# launch_pos.py
import os, sys, time, threading, webbrowser, pathlib

# Ensure project is importable
BASE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

# Use a writable data dir for SQLite on Windows
APP_NAME = "StationeryPOS"
APPDATA = os.environ.get("APPDATA", str(BASE))
DATA_DIR = pathlib.Path(APPDATA) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Tell settings where to keep the DB (so your settings can read this)
os.environ.setdefault("DJANGO_DB_PATH", str(DATA_DIR / "db.sqlite3"))

# Django settings module (adjust to your settings module path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stationery_pos.settings")

# Optional: make Django serve static files nicely in prod using WhiteNoise (if you added it)
# os.environ.setdefault("WHITENOISE_AUTOREFRESH", "false")

import django
from django.core.management import call_command

def open_browser_later(url):
    time.sleep(1.0)
    try:
        webbrowser.open(url)
    except Exception:
        pass

def main():
    django.setup()

    # Create DB / apply migrations (first run friendly)
    call_command("migrate", interactive=False, run_syncdb=True)

    # Optional: collect static if you use WhiteNoise + DEBUG=False
    # call_command("collectstatic", interactive=False, verbosity=0)

    url = "http://127.0.0.1:8000"
    threading.Thread(target=open_browser_later, args=(url,), daemon=True).start()

    # Easiest: run the built-in server for local/offline usage
    call_command("runserver", "127.0.0.1:8000", use_threading=True)

if __name__ == "__main__":
    main()
