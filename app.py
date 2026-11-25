"""Server lokal Soundboard Pentas.

Menyimpan metadata (suara, background, pengaturan) di SQLite (data/soundboard.db)
dan file audio/gambar/video sebagai file biasa di data/audio/ dan data/images/.
Hanya bisa diakses dari laptop ini (127.0.0.1).

Jalankan:  python app.py            (port 8765)
           python app.py --buka     (sekaligus membuka browser)
           python app.py --port 8766
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import webbrowser
import zipfile
from pathlib import Path

from flask import Flask, g, jsonify, request, send_file, send_from_directory

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DATA = BASE / "data"
AUDIO_DIR = DATA / "audio"
IMAGE_DIR = DATA / "images"
DB_PATH = DATA / "soundboard.db"

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
APP_ID = "soundboard-pentas"

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SETTING_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

AUDIO_TYPES = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
    ".aac": "audio/aac", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".flac": "audio/flac", ".webm": "audio/webm", ".audio": "application/octet-stream",
}
MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    ".gif": "image/gif", ".bmp": "image/bmp", ".avif": "image/avif",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
}

# Dua jenis data yang punya file: suara (audio) dan background (gambar/video).
KINDS = {
    "sounds": {
        "table": "sounds", "file_col": "audio_file", "dir": AUDIO_DIR, "types": AUDIO_TYPES,
        "flag": "hasAudio", "cols": ("cue", "name", "category"), "label": "Suara",
    },
    "backgrounds": {
        "table": "backgrounds", "file_col": "media_file", "dir": IMAGE_DIR, "types": MEDIA_TYPES,
        "flag": "hasMedia", "cols": ("cue", "name", "kind"), "label": "Background",
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sounds (
    id         TEXT PRIMARY KEY,
    cue        TEXT NOT NULL DEFAULT '',
    name       TEXT NOT NULL DEFAULT '',
    category   TEXT NOT NULL DEFAULT 'musik',
    data       TEXT NOT NULL,           -- seluruh pengaturan pad (JSON)
    audio_file TEXT,                    -- nama file di data/audio/
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS backgrounds (
    id         TEXT PRIMARY KEY,
    cue        TEXT NOT NULL DEFAULT '',
    name       TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT 'image',
    data       TEXT NOT NULL,           -- seluruh pengaturan background (JSON)
    media_file TEXT,                    -- nama file di data/images/
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                 -- JSON
);
"""

WRITE_LOCK = threading.Lock()
CHUNK = 1024 * 1024

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False
app.json.sort_keys = False


# ---------------------------------------------------------------- helpers
class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@app.errorhandler(ApiError)
def _api_error(e: ApiError):
    return jsonify(error=e.message), e.status


@app.errorhandler(404)
def _not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify(error="Alamat API tidak dikenal."), 404
    return "Halaman tidak ditemukan.", 404


@app.errorhandler(405)
def _bad_method(_e):
    return jsonify(error="Permintaan ini tidak didukung."), 405


@app.errorhandler(500)
def _server_error(_e):
    return jsonify(error="Terjadi kesalahan di server. Lihat jendela start.bat untuk detailnya."), 500


def init_storage() -> None:
    for d in (DATA, AUDIO_DIR, IMAGE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()


def db() -> sqlite3.Connection:
    if "db" not in g:
        con = sqlite3.connect(DB_PATH, timeout=30)
        con.row_factory = sqlite3.Row
        g.db = con
    return g.db


@app.teardown_appcontext
def _close_db(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def kind_cfg(kind: str) -> dict:
    cfg = KINDS.get(kind)
    if not cfg:
        raise ApiError("Alamat API tidak dikenal.", 404)
    return cfg


def check_id(item_id: str) -> str:
    if not ID_RE.match(item_id or ""):
        raise ApiError("ID tidak valid.")
    return item_id


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def row_to_item(row: sqlite3.Row, cfg: dict) -> dict:
    try:
        item = json.loads(row["data"])
    except (TypeError, ValueError):
        item = {}
    item["id"] = row["id"]
    fname = row[cfg["file_col"]]
    item[cfg["flag"]] = bool(fname) and (cfg["dir"] / fname).is_file()
    return item


def list_items(cfg: dict) -> list[dict]:
    rows = db().execute(f"SELECT * FROM {cfg['table']} ORDER BY cue COLLATE NOCASE, id").fetchall()
    return [row_to_item(r, cfg) for r in rows]


def read_settings() -> dict:
    out = {}
    for r in db().execute("SELECT key, value FROM settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except ValueError:
            pass
    return out


def clean_item(data: dict, cfg: dict, item_id: str) -> dict:
    item = {k: v for k, v in data.items() if k not in ("hasAudio", "hasMedia", "audioFile", "mediaFile")}
    item["id"] = item_id
    return item


def upsert_item(con: sqlite3.Connection, cfg: dict, item: dict, file_name: str | None = None,
                keep_file: bool = True) -> None:
    cols = cfg["cols"]
    values = [str(item.get(c, "") or "") for c in cols]
    if keep_file:
        con.execute(
            f"INSERT INTO {cfg['table']} (id, {', '.join(cols)}, data, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            f"ON CONFLICT(id) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in cols)}, "
            f"data=excluded.data, updated_at=excluded.updated_at",
            [item["id"], *values, json.dumps(item, ensure_ascii=False), time.time()],
        )
    else:
        con.execute(
            f"INSERT OR REPLACE INTO {cfg['table']} (id, {', '.join(cols)}, data, {cfg['file_col']}, updated_at) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?)",
            [item["id"], *values, json.dumps(item, ensure_ascii=False), file_name, time.time()],
        )


def ext_for(name: str, content_type: str, cfg: dict) -> str:
    ext = os.path.splitext(name or "")[1].lower()
    if ext == ".jpe":
        ext = ".jpg"
    if ext in cfg["types"]:
        return ext
    ctype = (content_type or "").split(";")[0].strip().lower()
    for e, t in cfg["types"].items():
        if t == ctype and e not in (".audio", ".oga", ".opus", ".m4v", ".jpeg"):
            return e
    if cfg is KINDS["sounds"]:
        return ".audio"
    raise ApiError("Jenis file ini tidak didukung. Pakai JPG, PNG, WEBP, GIF, atau video MP4/WEBM.")


def stream_to_temp(src, folder: Path) -> tuple[Path, int]:
    """Salin aliran data ke file sementara di folder tujuan (supaya rename-nya atomik)."""
    fd, tmp = tempfile.mkstemp(prefix=".upload-", suffix=".tmp", dir=folder)
    size = 0
    try:
        with os.fdopen(fd, "wb") as f:
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return Path(tmp), size


ID_FILE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\.[a-z0-9]{1,6}$")


def remove_file(folder: Path, name: str | None) -> None:
    if name and ID_FILE_RE.match(name):
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError:
            pass


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w\-. ]+", "", str(s), flags=re.ASCII).strip()
    return re.sub(r"\s+", "_", s)[:60] or "suara"


def natural_key(item: dict):
    parts = re.split(r"(\d+)", str(item.get("cue", "")).lower())
    return [(0, int(p)) if p.isdigit() else (1, p) for p in parts if p != ""]


# ---------------------------------------------------------------- keamanan sederhana
ALLOWED_HOSTS: set[str] = set()


@app.before_request
def _guard():
    # Tolak permintaan yang datang lewat nama host lain (mencegah DNS rebinding)
    host = (request.host or "").lower()
    if ALLOWED_HOSTS and host not in ALLOWED_HOSTS:
        return jsonify(error="Akses ditolak."), 403
    # Perubahan data hanya boleh dari halaman soundboard sendiri
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin and origin.lower().split("://", 1)[-1] not in ALLOWED_HOSTS:
            return jsonify(error="Akses ditolak."), 403
    return None


# ---------------------------------------------------------------- halaman
@app.get("/")
def index():
    resp = send_from_directory(STATIC, "index.html", max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/<path:filename>")
def static_files(filename: str):
    if filename.startswith("api/"):
        raise ApiError("Alamat API tidak dikenal.", 404)
    resp = send_from_directory(STATIC, filename, max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ---------------------------------------------------------------- API umum
@app.get("/api/ping")
def ping():
    return jsonify(app=APP_ID, ok=True)


@app.get("/api/state")
def get_state():
    return jsonify(
        sounds=list_items(KINDS["sounds"]),
        bgs=list_items(KINDS["backgrounds"]),
        settings=read_settings(),
    )


# ---------------------------------------------------------------- CRUD sounds / backgrounds
@app.get("/api/<kind>")
def list_kind(kind):
    return jsonify(list_items(kind_cfg(kind)))


@app.get("/api/<kind>/<item_id>")
def get_item(kind, item_id):
    cfg = kind_cfg(kind)
    row = db().execute(f"SELECT * FROM {cfg['table']} WHERE id=?", [check_id(item_id)]).fetchone()
    if not row:
        raise ApiError(f"{cfg['label']} tidak ditemukan.", 404)
    return jsonify(row_to_item(row, cfg))


@app.put("/api/<kind>/<item_id>")
def put_item(kind, item_id):
    cfg = kind_cfg(kind)
    check_id(item_id)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Data yang dikirim tidak valid.")
    if data.get("id") not in (None, item_id):
        raise ApiError("ID di data tidak sama dengan alamat.")
    item = clean_item(data, cfg, item_id)
    with WRITE_LOCK:
        con = db()
        with con:
            upsert_item(con, cfg, item)
        row = con.execute(f"SELECT * FROM {cfg['table']} WHERE id=?", [item_id]).fetchone()
    return jsonify(row_to_item(row, cfg))


@app.delete("/api/<kind>/<item_id>")
def delete_item(kind, item_id):
    cfg = kind_cfg(kind)
    check_id(item_id)
    with WRITE_LOCK:
        con = db()
        row = con.execute(f"SELECT {cfg['file_col']} FROM {cfg['table']} WHERE id=?", [item_id]).fetchone()
        if not row:
            raise ApiError(f"{cfg['label']} tidak ditemukan.", 404)
        with con:
            con.execute(f"DELETE FROM {cfg['table']} WHERE id=?", [item_id])
        remove_file(cfg["dir"], row[0])
    return jsonify(ok=True)


@app.put("/api/<kind>/<item_id>/file")
def put_file(kind, item_id):
    cfg = kind_cfg(kind)
    check_id(item_id)
    ext = ext_for(request.args.get("name", ""), request.content_type or "", cfg)
    if not db().execute(f"SELECT 1 FROM {cfg['table']} WHERE id=?", [item_id]).fetchone():
        raise ApiError(f"{cfg['label']} belum disimpan, jadi filenya belum bisa diunggah.", 404)
    tmp, size = stream_to_temp(request.stream, cfg["dir"])
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise ApiError("File yang dikirim kosong.")
    final = f"{item_id}{ext}"
    with WRITE_LOCK:
        con = db()
        row = con.execute(f"SELECT {cfg['file_col']} FROM {cfg['table']} WHERE id=?", [item_id]).fetchone()
        if not row:
            tmp.unlink(missing_ok=True)
            raise ApiError(f"{cfg['label']} sudah dihapus.", 404)
        try:
            os.replace(tmp, cfg["dir"] / final)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise ApiError("File tidak bisa disimpan. Mungkin file lama sedang dipakai program lain atau disk penuh.", 500)
        with con:
            con.execute(f"UPDATE {cfg['table']} SET {cfg['file_col']}=?, updated_at=? WHERE id=?",
                        [final, time.time(), item_id])
        if row[0] and row[0] != final:
            remove_file(cfg["dir"], row[0])
    return jsonify(ok=True, file=final, size=size)


@app.get("/api/<kind>/<item_id>/file")
def get_file(kind, item_id):
    cfg = kind_cfg(kind)
    row = db().execute(f"SELECT {cfg['file_col']} FROM {cfg['table']} WHERE id=?", [check_id(item_id)]).fetchone()
    if not row or not row[0] or not (cfg["dir"] / row[0]).is_file():
        raise ApiError("File tidak ditemukan.", 404)
    ext = os.path.splitext(row[0])[1].lower()
    return send_file(cfg["dir"] / row[0], mimetype=cfg["types"].get(ext, "application/octet-stream"),
                     max_age=0, conditional=True)


# ---------------------------------------------------------------- settings
@app.get("/api/settings")
def get_settings():
    return jsonify(read_settings())


@app.get("/api/settings/<key>")
def get_setting(key):
    if not SETTING_RE.match(key):
        raise ApiError("Nama pengaturan tidak valid.")
    row = db().execute("SELECT value FROM settings WHERE key=?", [key]).fetchone()
    if not row:
        raise ApiError("Pengaturan tidak ditemukan.", 404)
    return app.response_class(row[0], mimetype="application/json")


@app.put("/api/settings/<key>")
def put_setting(key):
    if not SETTING_RE.match(key):
        raise ApiError("Nama pengaturan tidak valid.")
    raw = request.get_data(as_text=True)
    try:
        value = json.loads(raw)
    except ValueError:
        raise ApiError("Data yang dikirim tidak valid.")
    with WRITE_LOCK:
        con = db()
        with con:
            con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                        [key, json.dumps(value, ensure_ascii=False)])
    return jsonify(ok=True)


@app.delete("/api/settings/<key>")
def delete_setting(key):
    if not SETTING_RE.match(key):
        raise ApiError("Nama pengaturan tidak valid.")
    with WRITE_LOCK:
        con = db()
        with con:
            con.execute("DELETE FROM settings WHERE key=?", [key])
    return jsonify(ok=True)


# ---------------------------------------------------------------- backup .zip
@app.get("/api/backup")
def backup():
    """Format sama dengan versi lama: soundboard.json + audio/<id>.<ext> + bg/<id>.<ext>."""
    snd, bgc = KINDS["sounds"], KINDS["backgrounds"]
    settings = read_settings().get("settings") or {}
    title = settings.get("title") or "Pertunjukan"
    meta = {"app": APP_ID, "version": 2, "title": title, "master": settings.get("master", 1),
            "sounds": [], "bgs": []}
    files: list[tuple[Path, str]] = []
    con = db()
    for cfg, key, prefix, attr in ((snd, "sounds", "audio", "audioFile"),
                                   (bgc, "bgs", "bg", "mediaFile")):
        rows = con.execute(f"SELECT * FROM {cfg['table']}").fetchall()
        entries = []
        for r in rows:
            item = row_to_item(r, cfg)
            if item[cfg["flag"]]:
                fname = r[cfg["file_col"]]
                arc = f"{prefix}/{item['id']}{os.path.splitext(fname)[1]}"
                item[attr] = arc
                files.append((cfg["dir"] / fname, arc))
            entries.append(item)
        meta[key] = sorted(entries, key=natural_key)
    tmp = tempfile.TemporaryFile()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        for path, arc in files:
            z.write(path, arc)
        z.writestr("soundboard.json", json.dumps(meta, ensure_ascii=False, indent=2))
    tmp.seek(0)
    # Header "attachment" hanya bila diminta (?unduh=1): halaman soundboard mengambil
    # file ini lewat fetch() dan sebagian browser mengosongkan respons fetch yang berlabel attachment.
    return send_file(tmp, mimetype="application/zip", as_attachment=request.args.get("unduh") == "1",
                     download_name=f"backup_{safe_name(title)}.zip", max_age=0)


# ---------------------------------------------------------------- impor / pulihkan .zip
@app.post("/api/import")
def import_zip():
    """Ganti isi soundboard dengan isi file backup .zip (format lama tetap didukung)."""
    tmp_zip, size = stream_to_temp(request.stream, DATA)
    staged: list[tuple[Path, Path]] = []
    try:
        if size == 0:
            raise ApiError("File yang dikirim kosong.")
        try:
            z = zipfile.ZipFile(tmp_zip)
        except (zipfile.BadZipFile, OSError):
            raise ApiError("File ini bukan backup soundboard.")
        with z:
            try:
                meta = json.loads(z.read("soundboard.json").decode("utf-8-sig"))
            except (zipfile.BadZipFile, KeyError, ValueError, UnicodeDecodeError, OSError):
                raise ApiError("File ini bukan backup soundboard.")
            if not isinstance(meta, dict) or not isinstance(meta.get("sounds"), list):
                raise ApiError("File ini bukan backup soundboard.")
            names = {i.filename for i in z.infolist() if not i.is_dir()}
            replace_bgs = isinstance(meta.get("bgs"), list)

            def take_id(raw, used: set) -> str:
                i = str(raw) if raw is not None else ""
                if not ID_RE.match(i) or i in used:
                    i = new_id()
                used.add(i)
                return i

            def stage(path, cfg, item_id, fallback_ext):
                if not isinstance(path, str) or path not in names:
                    return None
                ext = os.path.splitext(path)[1].lower()
                if ext == ".jpe":
                    ext = ".jpg"
                if ext not in cfg["types"]:
                    ext = fallback_ext
                final = f"{item_id}{ext}"
                with z.open(path) as src:
                    tmp, n = stream_to_temp(src, cfg["dir"])
                if n == 0:
                    tmp.unlink(missing_ok=True)
                    return None
                staged.append((tmp, cfg["dir"] / final))
                return final

            bg_items, bg_map = [], {}
            if replace_bgs:
                used: set = set()
                for b in meta["bgs"]:
                    if not isinstance(b, dict):
                        continue
                    old = b.get("id")
                    bid = take_id(old, used)
                    bg_map[str(old)] = bid
                    item = clean_item(b, KINDS["backgrounds"], bid)
                    fb = ".mp4" if b.get("kind") == "video" else ".jpg"
                    bg_items.append((item, stage(b.get("mediaFile"), KINDS["backgrounds"], bid, fb)))

            snd_items, used = [], set()
            for s in meta["sounds"]:
                if not isinstance(s, dict):
                    continue
                sid = take_id(s.get("id"), used)
                item = clean_item(s, KINDS["sounds"], sid)
                if replace_bgs and item.get("bgId"):
                    item["bgId"] = bg_map.get(str(item["bgId"]), "")
                snd_items.append((item, stage(s.get("audioFile"), KINDS["sounds"], sid, ".audio")))

        with WRITE_LOCK:
            con = db()
            old_files = {"sounds": [r[0] for r in con.execute("SELECT audio_file FROM sounds")]}
            if replace_bgs:
                old_files["backgrounds"] = [r[0] for r in con.execute("SELECT media_file FROM backgrounds")]
            settings = read_settings().get("settings") or {}
            settings["title"] = meta.get("title") or settings.get("title") or "The Invisible Tears"
            settings["master"] = meta.get("master") if isinstance(meta.get("master"), (int, float)) else 1
            if replace_bgs:
                settings["currentBg"] = None
            with con:
                con.execute("DELETE FROM sounds")
                for item, fname in snd_items:
                    upsert_item(con, KINDS["sounds"], item, fname, keep_file=False)
                if replace_bgs:
                    con.execute("DELETE FROM backgrounds")
                    for item, fname in bg_items:
                        upsert_item(con, KINDS["backgrounds"], item, fname, keep_file=False)
                put = "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)"
                con.execute(put, ["settings", json.dumps(settings, ensure_ascii=False)])
                con.execute(put, ["seeded", "true"])
                if replace_bgs:
                    con.execute(put, ["bgSeeded", "true"])
            for tmp, dest in staged:
                os.replace(tmp, dest)
            staged.clear()
            keep = {"sounds": {f for _, f in snd_items if f}, "backgrounds": {f for _, f in bg_items if f}}
            for kind, olds in old_files.items():
                for f in olds:
                    if f and f not in keep[kind]:
                        remove_file(KINDS[kind]["dir"], f)
        return jsonify(ok=True,
                       sounds=len(snd_items), soundFiles=sum(1 for _, f in snd_items if f),
                       bgs=len(bg_items) if replace_bgs else None,
                       bgFiles=sum(1 for _, f in bg_items if f) if replace_bgs else None)
    finally:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        tmp_zip.unlink(missing_ok=True)


# ---------------------------------------------------------------- start
def soundboard_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/ping", timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == APP_ID
    except Exception:
        return False


def port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Server lokal Soundboard Pentas")
    ap.add_argument("--port", type=int, default=int(os.environ.get("SOUNDBOARD_PORT", DEFAULT_PORT)))
    ap.add_argument("--buka", action="store_true", help="buka browser setelah server siap")
    args = ap.parse_args()
    port = args.port
    url = f"http://localhost:{port}"

    if soundboard_running(port):
        print(f"Soundboard sudah berjalan di {url}")
        if args.buka:
            webbrowser.open(url)
        return 0
    if not port_free(port):
        print()
        print(f"  [GAGAL] Port {port} sudah dipakai program lain.")
        print(f"  Pilihan 1: tutup program itu (atau restart laptop), lalu jalankan start.bat lagi.")
        print(f"  Pilihan 2: pakai port lain. Buka start.bat dengan Notepad, ubah angka {port}")
        print(f"             di baris  set \"SOUNDBOARD_PORT={port}\"  menjadi misalnya {port + 1},")
        print(f"             simpan, lalu jalankan start.bat lagi. Data tidak hilang.")
        print()
        return 2

    init_storage()
    ALLOWED_HOSTS.update({f"localhost:{port}", f"127.0.0.1:{port}"})

    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None

    print()
    print("  ===============================================")
    print("   SOUNDBOARD PENTAS - server lokal berjalan")
    print(f"   Buka di browser : {url}")
    print(f"   Data disimpan di: {DATA}")
    print("   JANGAN TUTUP jendela ini selama soundboard dipakai.")
    print("   Untuk berhenti: tutup jendela ini atau tekan Ctrl+C.")
    print("  ===============================================")
    print()

    if args.buka:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        app.run(host=HOST, port=port, threaded=True, use_reloader=False, debug=False)
    except OSError as e:
        print(f"  [GAGAL] Server tidak bisa dijalankan di port {port}: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
