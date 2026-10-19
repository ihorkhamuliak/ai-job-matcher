"""One process on the server (owner decision 07.10): listens to buttons and runs the scan itself at 12:00 and 22:00 Warsaw time,
a database backup at 03:00 (keeps 3), an encrypted copy to a chat every Sunday. No crontab and no touching the server's own backup:
the server is shared. The scan runs in this thread, buttons in a separate one with its own connection (store.connect waits)."""
import contextlib
import gzip
import hashlib
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from . import package, rank, scan, store, tg

SCANS = rank.ROOT / "data" / "scans"
BACKUPS = rank.ROOT / "data" / "backups"
BANK = rank.ROOT / "facts.yaml"  # 10.10: the main copy of the bank lives on the server, backed up together with the database
SLOTS = {"12:00": "scan", "22:00": "scan", "03:00": "backup"}
KEEP = 3


def run_scan(bot: tg.Bot, now) -> None:
    """Report to a file. The scan crashed or finished without a header -> red alert to the chat: silence = the bot is down."""
    SCANS.mkdir(parents=True, exist_ok=True)
    path = SCANS / f"{now:%Y-%m-%d_%H%M}.txt"
    try:
        with open(path, "w", encoding="utf-8") as f, contextlib.redirect_stdout(f):
            scan.main(["--tg"])
    except BaseException as ex:  # and SystemExit: a scan without network exits with code 2
        if isinstance(ex, KeyboardInterrupt):
            raise
        bot.send(f"🔴 Скан {now:%H:%M} упав: {tg.e(type(ex).__name__)}: {tg.e(str(ex)[:200])}\nФайл: {path.name}")
        traceback.print_exc()


PASS = Path("/run/backup-pass")  # read-only volume with the backup password: the same one as the server backup and the password manager


def encrypt(src: Path) -> Path:
    """gpg AES256 symmetric. Fail-closed: no password - an exception, never a plaintext file in the chat."""
    if not PASS.exists():
        raise RuntimeError(f"нема {PASS}, незашифроване не шлемо")
    out = src.with_name(src.name + ".gpg")
    subprocess.run(["gpg", "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback", "--passphrase-file", str(PASS),
                    "--symmetric", "--cipher-algo", "AES256", "-o", str(out), str(src)], check=True, capture_output=True)
    return out


def send_weekly(bot: tg.Bot, dest: Path, bank: Path, now) -> None:
    """Every Sunday to the backups channel (owner 11.10): the database always, the bank only when it changed since the last send."""
    chat = int(tg.env("TELEGRAM_BACKUPS_CHAT_ID") or bot.chat_id)
    gz = dest.with_suffix(".db.gz")
    with open(dest, "rb") as fi, gzip.open(gz, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    digest = hashlib.sha256(bank.read_bytes()).hexdigest()
    sent_mark = dest.parent / "bank-sent.sha256"
    files = [(gz, f"Бекап бази job-search, {now:%d.%m}")]
    if not sent_mark.exists() or sent_mark.read_text().strip() != digest:
        files.append((bank, f"Банк фактів CV змінився, {now:%d.%m}"))
    made = [gz]
    try:
        for src, caption in files:
            enc = encrypt(src)
            made.append(enc)
            with open(enc, "rb") as fh:
                bot.call("sendDocument", files={"document": (enc.name, fh)}, chat_id=chat,
                         caption=f"{caption} · gpg, пароль у менеджері паролів", disable_notification=True)
            if src == bank:
                sent_mark.write_text(digest)
    finally:
        for f in made:
            f.unlink(missing_ok=True)


def backup(bot: tg.Bot, now) -> None:
    """A consistent copy through the backup API (not cp of a live file), integrity_check; every Sunday the encrypted copy goes to the backups channel."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS / f"jobs-{now:%Y%m%d}.db"
    src, dst = sqlite3.connect(store.DB, timeout=30), sqlite3.connect(dest)
    try:
        src.backup(dst)
        (check,) = dst.execute("PRAGMA integrity_check").fetchone()
    finally:
        src.close()
        dst.close()
    if check != "ok":
        bot.send(f"🔴 Бекап бази {dest.name}: integrity_check = {tg.e(check)}")
        return
    bank = BACKUPS / f"facts-{now:%Y%m%d}.yaml"
    shutil.copyfile(BANK, bank)
    for pattern in ("jobs-*.db", "facts-*.yaml"):
        for old in sorted(BACKUPS.glob(pattern))[:-KEEP]:
            old.unlink()
    if now.weekday() == 6:
        try:
            send_weekly(bot, dest, bank, now)
        except Exception as ex:  # a week without an off-server copy must reach a human, not just docker logs
            bot.send(f"🔴 Тижневий бекап не надіслано: {tg.e(type(ex).__name__)}: {tg.e(str(ex)[:200])}")
            raise


def start_buttons(bot: tg.Bot) -> threading.Thread:
    """09.10, first day on the server: a connection from the main thread -> every button raised ProgrammingError
    (sqlite does not share connections between threads). So it is opened inside the buttons thread."""
    t = threading.Thread(target=lambda: tg.poll(store.connect(), bot), daemon=True)
    t.start()
    return t


def main() -> None:
    bot = tg.Bot.from_env()
    start_buttons(bot)
    print(f"serve: старт {rank.now_warsaw():%d.%m %H:%M} (Варшава), слоти {', '.join(SLOTS)}", file=sys.stderr, flush=True)
    done = set()
    while True:
        now = rank.now_warsaw()
        slot = f"{now:%H:%M}"
        if slot in SLOTS and (now.date(), slot) not in done:
            done.add((now.date(), slot))
            try:
                run_scan(bot, now) if SLOTS[slot] == "scan" else backup(bot, now)
            except Exception:  # even the red alert did not get through - it stays in docker logs, the process keeps running
                traceback.print_exc()
        try:
            package.archive()  # 19.10: CVs older than an hour -> archive/, the laptop mirrors this into its archive folder
        except Exception:
            traceback.print_exc()
        time.sleep(20)


if __name__ == "__main__":
    main()
