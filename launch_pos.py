# launch_pos.py
import os, sys, time, threading, webbrowser, pathlib, traceback

# -------------------------
# App constants & paths
# -------------------------
APP_NAME = "StationeryPOS"
BASE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

APPDATA = os.environ.get("APPDATA", str(BASE))  # per-user writable
DATA_DIR = pathlib.Path(APPDATA) / APP_NAME
LOG_DIR = DATA_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "app.log"

# -------------------------
# Ensure stdout/stderr exist (EXE with console=False → None)
# -------------------------
if sys.stdout is None:
    sys.stdout = open(LOG_FILE, "a", buffering=1, encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = sys.stdout

def log(msg: str):
    try:
        print(msg, file=sys.stdout, flush=True)
    except Exception:
        pass

# -------------------------
# Environment for Django
# -------------------------
os.environ.setdefault("DJANGO_DB_PATH", str(DATA_DIR / "db.sqlite3"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stationery_pos.settings")
os.environ.setdefault("PORT", "8000")  # change via env or .env

# Optional (if using WhiteNoise + DEBUG=False)
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
    log("Launcher starting…")
    log(f"DATA_DIR={DATA_DIR}")
    log(f"LOG_FILE={LOG_FILE}")

    django.setup()

    # First-run friendly: migrate (safe to re-run)
    log("Running migrations…")
    call_command("migrate", interactive=False, run_syncdb=True,
                 stdout=sys.stdout, stderr=sys.stderr)

    # If you serve static via WhiteNoise in production, uncomment next line
    # log("Collecting static…")
    # call_command("collectstatic", interactive=False, verbosity=0,
    #              stdout=sys.stdout, stderr=sys.stderr)

    port = os.environ.get("PORT", "8000")
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=open_browser_later, args=(url,), daemon=True).start()

    # Local server for offline usage (simple & fine for single-user POS)
    log(f"Starting runserver at {url} …")
    call_command("runserver", f"127.0.0.1:{port}", use_threading=True,
                 stdout=sys.stdout, stderr=sys.stderr)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log full traceback
        tb = traceback.format_exc()
        log("FATAL ERROR:\n" + tb)

        # Optional: show a Windows message box for non-technical users
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                f"StationeryPOS failed to start.\n\nSee log:\n{LOG_FILE}\n\n{tb}",
                "StationeryPOS Error",
                0x00000010  # MB_ICONERROR
            )
        except Exception:
            pass

        # Exit non-zero so installer/OS knows it failed
        sys.exit(1)
