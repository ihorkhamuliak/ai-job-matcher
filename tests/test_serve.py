"""serve.py, 09.10: on the first day on the server the buttons failed with ProgrammingError - the database connection was opened in another thread."""
import sqlite3

from jobbot import serve, store, tg


def test_buttons_thread_uses_db_opened_in_its_own_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "connect", lambda: sqlite3.connect(tmp_path / "t.db"))  # like the real one: check_same_thread
    errors = []

    def poll(db, bot):
        try:
            db.execute("SELECT 1")
        except Exception as ex:
            errors.append(ex)
    monkeypatch.setattr(tg, "poll", poll)
    serve.start_buttons(None).join(5)
    assert errors == []


class Sent:
    def __init__(self):
        self.docs, self.chats = [], []

    def call(self, method, files=None, **kw):
        self.docs.append(files["document"][0])
        self.chats.append(kw["chat_id"])

    def send(self, text):
        self.docs.append(text)

    chat_id = 1


def fake_gpg(src):
    out = src.with_name(src.name + ".gpg")
    out.write_bytes(b"\x8c\x0d" + src.read_bytes()[::-1])  # neither plaintext nor gzip
    return out


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", tmp_path / "jobs.db")
    store.connect(tmp_path / "jobs.db").close()
    bank = tmp_path / "facts.yaml"
    bank.write_text("skills: {}\n", encoding="utf-8")
    monkeypatch.setattr(serve, "BANK", bank)
    monkeypatch.setattr(serve, "BACKUPS", tmp_path / "backups")
    monkeypatch.setattr(tg, "env", lambda name: "-100777" if name == "TELEGRAM_BACKUPS_CHAT_ID" else None)
    return bank


def test_bank_backed_up_nightly_and_sent_encrypted_on_sunday_only_when_changed(tmp_path, monkeypatch):
    """10.10: the bank's main copy lives on the server - copied every night. 11.10 (owner): every Sunday to the backups channel, gpg only,
    the bank only when it changed; after sending, neither .gz nor .gpg stays on disk."""
    from datetime import datetime
    bank = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(serve, "encrypt", fake_gpg)
    bot = Sent()
    serve.backup(bot, datetime(2026, 10, 10, 3, 0))  # Saturday
    assert (tmp_path / "backups" / "facts-20261010.yaml").read_text(encoding="utf-8") == "skills: {}\n"
    assert bot.docs == []
    serve.backup(bot, datetime(2026, 10, 11, 3, 0))  # Sunday
    assert bot.docs == ["jobs-20261011.db.gz.gpg", "facts-20261011.yaml.gpg"] and bot.chats == [-100777, -100777]
    assert not list((tmp_path / "backups").glob("*.g*"))
    serve.backup(bot, datetime(2026, 10, 18, 3, 0))  # the bank is the same - database only
    assert bot.docs[2:] == ["jobs-20261018.db.gz.gpg"]
    bank.write_text("skills: {python: 1}\n", encoding="utf-8")
    serve.backup(bot, datetime(2026, 10, 25, 3, 0))
    assert bot.docs[3:] == ["jobs-20261025.db.gz.gpg", "facts-20261025.yaml.gpg"]


def test_no_password_sends_nothing_open_and_says_red(tmp_path, monkeypatch):
    """Fail-closed (lesson 07.09): no password - no file goes to the chat, a red alert to the human."""
    import pytest
    from datetime import datetime
    setup(tmp_path, monkeypatch)
    monkeypatch.setattr(serve, "PASS", tmp_path / "nope")
    bot = Sent()
    with pytest.raises(RuntimeError):
        serve.backup(bot, datetime(2026, 10, 11, 3, 0))
    assert len(bot.docs) == 1 and bot.docs[0].startswith("🔴 Тижневий бекап не надіслано: RuntimeError: нема")
    assert not list((tmp_path / "backups").glob("*.g*"))
