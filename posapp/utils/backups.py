# posapp/utils/backups.py
import os, io, gzip, shutil, tempfile, subprocess, datetime
from pathlib import Path
from django.conf import settings
from django.core.management import call_command

def timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def default_backup_dir() -> Path:
    base = getattr(settings, "BACKUP_DIR", None)
    if base:
        p = Path(base)
    else:
        # fallback to <BASE_DIR>/backups
        p = Path(getattr(settings, "BASE_DIR", Path.cwd())) / "backups"
    _ensure_dir(p)
    return p

def create_db_backup(out_dir: Path | None = None) -> Path:
    """
    Returns a Path to the created backup file.
    - SQLite: copies .sqlite3 (gz)
    - Postgres: pg_dump custom format (gz)
    - MySQL: mysqldump (gz)
    - Fallback: Django dumpdata (gz)
    """
    out_dir = out_dir or default_backup_dir()
    _ensure_dir(out_dir)
    ts = timestamp()

    db = settings.DATABASES["default"]
    engine = db["ENGINE"]
    name = db["NAME"]
    user = db.get("USER") or ""
    password = db.get("PASSWORD") or ""
    host = db.get("HOST") or ""
    port = str(db.get("PORT") or "")

    # --- SQLite
    if "sqlite" in engine:
        src = Path(name).resolve()
        if not src.exists():
            raise FileNotFoundError(f"SQLite file not found: {src}")
        dst = out_dir / f"db_sqlite_{ts}.sqlite3.gz"
        with open(src, "rb") as fsrc, gzip.open(dst, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst)
        return dst

    # --- Postgres
    if "postgresql" in engine or "postgres" in engine:
        # requires pg_dump in PATH; use custom format for speed (-Fc)
        dst = out_dir / f"db_pg_{ts}.dump.gz"
        cmd = ["pg_dump", "-h", host or "localhost", "-p", port or "5432", "-U", user, "-Fc", name]
        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password
        with gzip.open(dst, "wb") as gz:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            out, err = p.communicate()
            if p.returncode != 0:
                raise RuntimeError(f"pg_dump failed: {err.decode('utf-8', 'ignore')}")
            gz.write(out)
        return dst

    # --- MySQL/MariaDB
    if "mysql" in engine:
        dst = out_dir / f"db_mysql_{ts}.sql.gz"
        cmd = ["mysqldump"]
        if host: cmd += ["-h", host]
        if port: cmd += ["-P", port]
        if user: cmd += ["-u", user]
        # safer to pass password via env to avoid shell history; mysqldump needs --password=xxx
        if password: cmd += [f"--password={password}"]
        cmd += ["--single-transaction", "--quick", name]
        with gzip.open(dst, "wb") as gz:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            if p.returncode != 0:
                raise RuntimeError(f"mysqldump failed: {err.decode('utf-8', 'ignore')}")
            gz.write(out)
        return dst

    # --- Fallback: Django JSON fixture
    dst = out_dir / f"db_dumpdata_{ts}.json.gz"
    buf = io.StringIO()
    call_command("dumpdata", "--natural-foreign", "--natural-primary", "--indent", "2", stdout=buf)
    with gzip.open(dst, "wb") as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    return dst
