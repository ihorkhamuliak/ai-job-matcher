import json
import sqlite3
import statistics
import time
from pathlib import Path

from . import config
from .job import Job

DB = Path(__file__).resolve().parent.parent / "data" / "jobs.db"


def connect(path: Path = DB) -> sqlite3.Connection:
    path.parent.mkdir(exist_ok=True)
    # The scan and Telegram buttons write from different threads: wait up to 30 s instead of 'database is locked' (07.10)
    db = sqlite3.connect(path, timeout=30)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS seen (
            key TEXT PRIMARY KEY, first_seen REAL, source TEXT, title TEXT, company TEXT, url TEXT);
        CREATE TABLE IF NOT EXISTS source_yield (
            ts REAL, source TEXT, query TEXT, raw INTEGER, error TEXT);
        CREATE TABLE IF NOT EXISTS texts (
            url TEXT PRIMARY KEY, source TEXT, fetched REAL, text TEXT, fails INTEGER DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS scores (
            url TEXT PRIMARY KEY, ts REAL, model TEXT, score INTEGER, result TEXT, cost REAL);
        -- Step 5a: a posting reaches Telegram once (seen is not touched: it would drop it from the model queue).
        -- the id goes into the button because a URL does not fit into 64 bytes of callback_data
        CREATE TABLE IF NOT EXISTS sent (
            id INTEGER PRIMARY KEY, url TEXT UNIQUE, ts REAL, message_id INTEGER);
        -- Button action: applied / dislike; undo deletes the row
        CREATE TABLE IF NOT EXISTS actions (
            url TEXT PRIMARY KEY, kind TEXT, reason TEXT, ts REAL);
        -- Step 4 (10.10): the model's choice per posting (CV rebuilt without the model) and gaps with the owner's answers.
        -- Answers extend the facts bank (facts.yaml is not rewritten: it holds comments)
        CREATE TABLE IF NOT EXISTS packages (
            url TEXT PRIMARY KEY, choice TEXT, raw TEXT, ts REAL);
        CREATE TABLE IF NOT EXISTS gaps (
            id INTEGER PRIMARY KEY, url TEXT, skill TEXT, category TEXT, level TEXT, ts REAL);
    """)
    # 5b (10.10): card data for the applications sheet row; the server database predates this column
    if "meta" not in {r[1] for r in db.execute("PRAGMA table_info(sent)")}:
        db.execute("ALTER TABLE sent ADD COLUMN meta TEXT")
        db.commit()
    # 10.10: the package PDF message - a new CV after a gap answer replaces the file in the same message
    if "message_id" not in {r[1] for r in db.execute("PRAGMA table_info(packages)")}:
        db.executescript("ALTER TABLE packages ADD COLUMN message_id INTEGER; ALTER TABLE packages ADD COLUMN caption TEXT;")
    return db


def sent_id(db, url: str) -> int | None:
    row = db.execute("SELECT id FROM sent WHERE url = ?", (url,)).fetchone()
    return row[0] if row else None


def sent_url(db, sid: int) -> str | None:
    row = db.execute("SELECT url FROM sent WHERE id = ?", (sid,)).fetchone()
    return row[0] if row else None


def mark_sent(db, url: str, message_id: int | None = None, meta: dict | None = None) -> int:
    cur = db.execute("INSERT INTO sent (url, ts, message_id, meta) VALUES (?, ?, ?, ?)",
                     (url, time.time(), message_id, json.dumps(meta, ensure_ascii=False) if meta else None))
    db.commit()
    return cur.lastrowid


def sent_meta(db, url: str) -> dict:
    row = db.execute("SELECT meta FROM sent WHERE url = ?", (url,)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def update_meta(db, url: str, **kv) -> None:
    """11.10: where the package lives (channel) and the card's original before collapsing - in the same card data."""
    db.execute("UPDATE sent SET meta = ? WHERE url = ?", (json.dumps({**sent_meta(db, url), **kv}, ensure_ascii=False), url))
    db.commit()


def unmark_sent(db, sid: int) -> None:
    db.execute("DELETE FROM sent WHERE id = ?", (sid,))
    db.commit()


def stale(db, hours: float = 48) -> list[tuple[int, float]]:
    """(score, sent at) for scored cards without a box/thumbs-down action older than hours. The letters block has no score and is not counted."""
    rows = db.execute("SELECT s.ts, s.meta FROM sent s LEFT JOIN actions a ON a.url = s.url "
                      "WHERE a.url IS NULL AND s.ts < ?", (time.time() - hours * 3600,))
    return [(meta["score"], ts) for ts, m in rows if m and "score" in (meta := json.loads(m))]


def set_message(db, sid: int, message_id: int) -> None:
    db.execute("UPDATE sent SET message_id = ? WHERE id = ?", (message_id, sid))
    db.commit()


def save_package(db, url: str, choice: dict, raw: dict) -> None:
    db.execute("INSERT OR REPLACE INTO packages (url, choice, raw, ts) VALUES (?, ?, ?, ?)",
               (url, json.dumps(choice, ensure_ascii=False), json.dumps(raw, ensure_ascii=False), time.time()))
    db.commit()


def set_package_message(db, url: str, message_id: int, caption: str) -> None:
    db.execute("UPDATE packages SET message_id = ?, caption = ? WHERE url = ?", (message_id, caption, url))
    db.commit()


def package_message(db, url: str) -> tuple[int, str] | None:
    row = db.execute("SELECT message_id, caption FROM packages WHERE url = ?", (url,)).fetchone()
    return (row[0], row[1]) if row and row[0] else None


def package(db, url: str) -> tuple[dict, dict] | None:
    row = db.execute("SELECT choice, raw FROM packages WHERE url = ?", (url,)).fetchone()
    return (json.loads(row[0]), json.loads(row[1])) if row else None


def add_gap(db, url: str, skill: str, category: str) -> int:
    cur = db.execute("INSERT INTO gaps (url, skill, category, ts) VALUES (?, ?, ?, ?)", (url, skill, category, time.time()))
    db.commit()
    return cur.lastrowid


def answer_gap(db, gid: int, level: str) -> tuple[str, str] | None:
    """(url, skill) or None if there is no question."""
    row = db.execute("SELECT url, skill FROM gaps WHERE id = ?", (gid,)).fetchone()
    if row:
        db.execute("UPDATE gaps SET level = ?, ts = ? WHERE id = ?", (level, time.time(), gid))
        db.commit()
    return row


def answers(db) -> list[tuple]:
    """(skill, level, category) - the latest answer for each skill."""
    rows = db.execute("SELECT skill, level, category FROM gaps WHERE level IS NOT NULL ORDER BY ts").fetchall()
    return list({s.lower(): (s, lvl, cat) for s, lvl, cat in rows}.values())


def set_action(db, url: str, kind: str, reason: str = "") -> None:
    db.execute("INSERT OR REPLACE INTO actions VALUES (?, ?, ?, ?)", (url, kind, reason, time.time()))
    db.commit()


def clear_action(db, url: str) -> None:
    db.execute("DELETE FROM actions WHERE url = ?", (url,))
    db.commit()


def action(db, url: str) -> str | None:
    row = db.execute("SELECT kind FROM actions WHERE url = ?", (url,)).fetchone()
    return row[0] if row else None


def score_row(db, url: str) -> dict | None:
    row = db.execute("SELECT score, result, model FROM scores WHERE url = ?", (url,)).fetchone()
    return {**json.loads(row[1]), "score": row[0], "model": row[2]} if row else None


def save_score(db, url: str, model: str, data: dict, cost: float) -> None:
    db.execute("INSERT OR REPLACE INTO scores VALUES (?, ?, ?, ?, ?, ?)",
               (url, time.time(), model, data["score"], json.dumps(data, ensure_ascii=False), cost))
    db.commit()


def text_row(db, url: str) -> tuple[str, int]:
    """(text or '', how many times fetching failed)."""
    row = db.execute("SELECT text, fails FROM texts WHERE url = ?", (url,)).fetchone()
    return (row[0] or "", row[1]) if row else ("", 0)


def save_text(db, job: Job, text: str) -> None:
    db.execute("INSERT OR REPLACE INTO texts VALUES (?, ?, ?, ?, 0, NULL)", (job.url, job.source, time.time(), text))
    db.commit()


def text_failed(db, job: Job, error: str) -> None:
    db.execute("INSERT INTO texts VALUES (?, ?, ?, NULL, 1, ?) "
               "ON CONFLICT(url) DO UPDATE SET fails = fails + 1, error = excluded.error, fetched = excluded.fetched",
               (job.url, job.source, time.time(), error))
    db.commit()


def is_seen(db, key: str) -> bool:
    return db.execute("SELECT 1 FROM seen WHERE key = ?", (key,)).fetchone() is not None


def mark_seen(db, job: Job) -> None:
    db.execute("INSERT OR IGNORE INTO seen VALUES (?, ?, ?, ?, ?, ?)",
               (job.key, time.time(), job.source, job.title, job.company, job.url))
    db.commit()


def source_status(raw: int, error: str | None, history: list[int], bad: int = 0, note: str = "") -> tuple[str, str]:
    """The sensor counts RAW items before filters, so a filter cannot mask a dead source."""
    if error:
        return "🔴", f"помилка {error}"
    if raw == 0:
        if note == config.CONFIRMED_EMPTY:
            return "⚪", note
        return "🔴", "0 сирих позицій"
    tail = (f" · не розібрано {bad}" if bad else "") + (f" · {note}" if note else "")
    if history:
        med = statistics.median(history)
        if raw < med * config.YIELD_DROP_RATIO:
            return "🟡", f"{raw} сирих, звично ~{med:.0f}{tail}"
    return ("🟡" if bad or note else "✅"), f"{raw} сирих{tail}"


def last_good_scan(db, since: float, total: int) -> float | None:
    """When the last successful scan after since finished. Successful = at least half of the queries passed
    without an error: otherwise a half-scan (network dropped on the third site) would eat the next slot."""
    n, last = db.execute("SELECT COUNT(*), MAX(ts) FROM source_yield WHERE ts > ? AND error IS NULL",
                         (since,)).fetchone()
    return last if n * 2 >= total else None


def log_yield(db, source: str, query: str, raw: int, error: str | None, bad: int = 0, note: str = "",
              since: float | None = None) -> tuple[str, str]:
    """since: the source returned only the N newest, and the oldest of them was published then (one board).
    If that is later than the previous scan, postings we never saw may have appeared in between."""
    now = time.time()
    if since and not error:
        (last,) = db.execute("SELECT MAX(ts) FROM source_yield WHERE source = ? AND query = ? AND error IS NULL",
                             (source, query)).fetchone()
        if last and since > last:
            gap = f"можливий пропуск: найновіші сягають {(now - since) / 3600:.0f} год, минулий скан {(now - last) / 3600:.0f} год тому"
            note = f"{note} · {gap}" if note else gap
    week_ago = now - 7 * 86400
    history = [r for (r,) in db.execute(
        "SELECT raw FROM source_yield WHERE source = ? AND query = ? AND ts > ? AND error IS NULL AND raw > 0",
        (source, query, week_ago))]
    status = source_status(raw, error, history, bad, note)
    db.execute("INSERT INTO source_yield VALUES (?, ?, ?, ?, ?)", (time.time(), source, query, raw, error))
    db.commit()
    return status
