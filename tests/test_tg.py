"""Step 5a, 07.10: digest in Telegram and buttons (owner decisions 06-07.10). No network: a fake http."""
import json
import time
import types

import pytest

from jobbot import config, rank, store, tg
from jobbot.job import Job

CHAT = 100000001


class FakeHttp:
    def __init__(self, fail_on=None):
        self.posts, self.fail_on, self.n = [], fail_on, 100

    def post(self, url, json=None, data=None, files=None):
        method = url.rsplit("/", 1)[1]
        self.posts.append((method, json or {**(data or {}), **(files or {})}))
        if self.fail_on and len([p for p in self.posts if p[0] == "sendMessage"]) == self.fail_on:
            return types.SimpleNamespace(json=lambda: {"ok": False, "description": "Bad Request"})
        self.n += 1
        return types.SimpleNamespace(json=lambda: {"ok": True, "result": {"message_id": self.n}})

    def sent(self):
        return [p for m, p in self.posts if m == "sendMessage"]


def job(i, title="Automation Specialist"):
    return Job("pracuj", title, "Acme", f"https://x/{i}", time.time(), "PL", cities=["Poznań"])


def ranked(worthy, note=""):
    return {"worthy": worthy, "scored": 3, "cost": 0.02, "waiting": 7, "note": note}


def worthy(n):
    return [(8, job(i), {"why": "збіг", "missing": ["Jira"]}) for i in range(n)]


STATUSES = [("pracuj", "python", "✅", "1200 сирих"), ("dou", "n8n", "🔴", "0 сирих позицій")]


@pytest.fixture
def db(tmp_path):
    return store.connect(tmp_path / "t.db")


def bot(http=None):
    return tg.Bot("TOKEN", CHAT, http or FakeHttp())


def test_header_always_sent_even_without_vacancies(db):
    b = bot()
    n = tg.send_scan(db, b, STATUSES, ranked([]), {}, rank.now_warsaw().replace(hour=12))
    sent = b.http.sent()
    assert n == 0 and len(sent) == 1
    assert "нових 5+: <b>0</b>" in sent[0]["text"] and "🔴 dou · n8n" in sent[0]["text"]
    assert sent[0]["text"].startswith("🔴")  # a red source is visible as the first character


def test_paused_header_is_silent_even_at_noon(db):
    b = bot()
    tg.send_scan(db, b, STATUSES[:1], ranked([], note="⏸ пауза"), {}, rank.now_warsaw().replace(hour=12))
    assert b.http.sent()[0]["disable_notification"] is True


def test_header_shows_group0_left_over_the_cap():
    assert "🟡 Познань/віддалено чекає стелі: 4" in tg.header(rank.now_warsaw(), STATUSES, {**ranked([]), "waiting0": 4}, 0)
    assert "Познань/віддалено" not in tg.header(rank.now_warsaw(), STATUSES, ranked([]), 0)


def test_header_counts_cards_left_without_reaction(db):
    """Sensor 19.10: a week of digests (12 cards, five of them 8+) passed without a single box or thumbs-down, and nothing showed it.
    Counted: scored cards without an action older than 2 days; thumbs-down, titles from letters and fresh ones are not."""
    old = time.time() - 5 * 86400
    for url, meta, act in (("https://x/a", {"score": 8}, None), ("https://x/b", {"score": 6}, "dislike"),
                           ("https://x/c", {"title": "з листа"}, None)):
        store.mark_sent(db, url, meta=meta)
        db.execute("UPDATE sent SET ts = ? WHERE url = ?", (old, url))
        if act:
            store.set_action(db, url, act)
    store.mark_sent(db, "https://x/d", meta={"score": 9})
    db.commit()
    b = bot()
    tg.send_scan(db, b, STATUSES[:1], ranked([]), {}, rank.now_warsaw())
    assert "⏳ карток без 📦/👎 понад 2 дн: 1 (8+: 1), найстарша 5 дн" in b.http.sent()[0]["text"]
    assert "без 📦/👎" not in tg.header(rank.now_warsaw(), STATUSES, ranked([]), 0)


def test_balance_note_makes_header_red(db):
    b = bot()
    tg.send_scan(db, b, STATUSES[:1], ranked([], note="🔴 баланс API скінчився"), {}, rank.now_warsaw())
    assert b.http.sent()[0]["text"].startswith("🔴")


def test_each_vacancy_once_and_new_ones_beyond_top10_come_next(db, monkeypatch):
    """Sent ones are dropped BEFORE the top cut: otherwise the 11th new one would never arrive."""
    monkeypatch.setattr(config, "DIGEST_TOP", 2)
    b = bot()
    when = rank.now_warsaw().replace(hour=12)
    assert tg.send_scan(db, b, STATUSES, ranked(worthy(3)), {}, when) == 2
    assert tg.send_scan(db, b, STATUSES, ranked(worthy(3)), {}, when) == 1  # third
    assert tg.send_scan(db, b, STATUSES, ranked(worthy(3)), {}, when) == 0
    urls = [p["text"].split('href="', 1)[1].split('"', 1)[0] for p in b.http.sent() if "reply_markup" in p]
    assert urls == ["https://x/0", "https://x/1", "https://x/2"]


def test_evening_is_silent_noon_is_not(db):
    b = bot()
    tg.send_scan(db, b, STATUSES, ranked(worthy(1)), {}, rank.now_warsaw().replace(hour=22))
    tg.send_scan(db, b, STATUSES, ranked([]), {}, rank.now_warsaw().replace(hour=12))
    flags = [p["disable_notification"] for p in b.http.sent()]
    assert flags == [True, True, False]


def test_failed_send_is_retried_next_scan(db):
    b = bot(FakeHttp(fail_on=2))  # 1 - header, 2 - the first posting
    with pytest.raises(RuntimeError):
        tg.send_scan(db, b, STATUSES, ranked(worthy(1)), {}, rank.now_warsaw())
    assert store.sent_id(db, "https://x/0") is None


def test_site_text_is_escaped(db):
    """Requirement 15: a title from a site does not break the HTML and does not inject markup."""
    j = job(0, title="Dev <b>R&D</b>")
    text = tg.card(8, j, {"why": "a < b", "missing": []}, ["⚠️ офіс: <Gdańsk>"])
    assert "<b>R&amp;D</b>" not in text and "Dev &lt;b&gt;R&amp;D&lt;/b&gt;" in text
    assert "a &lt; b" in text and "&lt;Gdańsk&gt;" in text


def test_card_title_is_the_link_and_url_cannot_leave_href():
    """Visual 10.10 (owner decision): title = link, no plain URL, blocks separated by an empty line."""
    j = job(0)
    j.url = 'https://x/0?a=1&b="><b>x'
    text = tg.card(9, j, {"why": "збіг", "missing": ["Excel"]}, ["⚠️ офіс: Gdańsk"])
    assert '<a href="https://x/0?a=1&amp;b=&quot;&gt;&lt;b&gt;x"><b>Automation Specialist</b></a>' in text
    assert text.count("https://x/0") == 1
    assert text.startswith("🟢 <b>9/10</b>") and "\n\n💬 збіг\n\n⚠️ офіс: Gdańsk\n➕ бракує: Excel" in text
    assert tg.card(7, job(1), {"why": "", "missing": []}, []).startswith("🟡")


def test_olx_company_is_shown_as_profile_name_but_key_stays():
    """12.10: OLX gives a profile name, not the employer. Displayed with a suffix; the dedup key stays without it,
    otherwise every OLX posting would become 'new' a second time."""
    j = Job("olx", "Młodszy Specjalista IT", "AGENCJA", "https://x/olx", time.time(), "PL", cities=["Poznań"])
    assert "🏢 AGENCJA (профіль OLX) · " in tg.card(7, j, {"why": "", "missing": []}, [])
    assert j.key == Job("olx", "Młodszy Specjalista IT", "AGENCJA", "u", 0, "PL").key and "профіль" not in j.key
    assert "🏢 Acme · " in tg.card(7, job(0), {"why": "", "missing": []}, [])
    assert tg.collapsed({"title": "T", "company": "AGENCJA", "source": "olx.pl"}, "https://x").endswith(
        "· AGENCJA (профіль OLX)")


def test_card_shows_extract_and_old_scores_without_it_still_render():
    """Extract 10.10 (owner decision): tasks, requirements, stack <= 8, offer, contract, mode and age; unknown is not shown."""
    j = job(0)
    j.mode, j.posted_at = "hybrid", time.time() - 3 * 86400 - 60
    s = {"why": "збіг", "matched": ["n8n", "SQL"], "missing": ["Excel"], "tasks": ["Build automations"],
         "requirements": ["Basic SQL", "Polish B2"], "stack": [f"t{i}" for i in range(12)], "offer": ["Training"],
         "contract": "UoP/B2B"}
    text = tg.card(9, j, s, [])
    for part in ("📍 Poznań · pracuj.pl\n", "💰 без вилки · 📄 UoP/B2B", "🏠 гібрид · 🕒 3 дн тому", "🛠 задачі: Build automations",
                 "📋 вимоги: Basic SQL; Polish B2", "🧰 стек: t0, t1, t2, t3, t4, t5, t6, t7\n", "🎁 пропонують: Training",
                 "✔️ є: n8n, SQL", "➕ бракує: Excel"):
        assert part in text, part
    old = tg.card(8, job(1), {"why": "збіг", "missing": [], "contract": "unknown"}, [])
    assert "📄" not in old and "🛠" not in old and "🕒 сьогодні" in old


# --- buttons

def press(db, b, data, user=CHAT, chat=CHAT, mid=7):
    tg.handle(db, b, {"update_id": 1, "callback_query": {
        "id": "q", "data": data, "from": {"id": user}, "message": {"message_id": mid, "chat": {"id": chat}}}})


def test_applied_then_undo_leaves_no_record(db, monkeypatch):
    fake_package(monkeypatch)
    b = bot()
    sid = store.mark_sent(db, "https://x/0", 7)
    press(db, b, f"p:{sid}")
    assert store.action(db, "https://x/0") == "applied"
    edit = [p for m, p in b.http.posts if m == "editMessageReplyMarkup"][-1]
    assert edit["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"u:{sid}"
    press(db, b, f"u:{sid}")
    assert store.action(db, "https://x/0") is None
    edit = [p for m, p in b.http.posts if m == "editMessageReplyMarkup"][-1]
    assert [k["callback_data"] for k in edit["reply_markup"]["inline_keyboard"][0]] == [f"d:{sid}", f"p:{sid}"]


class FakeSheet:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def append(self, url, meta, today):
        self.calls.append(("add", url, meta))
        if self.fail:
            raise RuntimeError("Sheets 503")
        return 19, True

    def remove(self, url):
        self.calls.append(("undo", url, None))
        return "removed"


def answers(b):
    return [p.get("text") for m, p in b.http.posts if m == "answerCallbackQuery"]


def card_msg(text="🟢 8/10 · Automation Specialist"):
    return {"message_id": 7, "chat": {"id": CHAT}, "text": text, "entities": []}


def test_package_is_the_application_row_goes_to_sheet_and_undo_takes_it_back(db, monkeypatch):
    """12.10 (owner 11.10): box 'applying' = package + application + a row with card data and CV; the row number goes into the collapsed
    card; undo -> remove; a repeated box takes the existing package; undo after thumbs-down does not touch the sheet."""
    calls = fake_package(monkeypatch)
    b, s = bot(), FakeSheet()
    tg.send_scan(db, b, STATUSES, ranked(worthy(1)), {}, rank.now_warsaw())
    sid = store.sent_id(db, "https://x/0")
    assert store.sent_meta(db, "https://x/0") == {"title": "Automation Specialist", "company": "Acme",
                                                   "where": "Poznań", "source": "pracuj.pl", "score": 8,
                                                   "missing": ["Jira"]}
    tap = lambda data: tg.handle(db, b, {"callback_query": {"id": "q", "data": data, "from": {"id": CHAT},
                                                            "message": card_msg()}}, s)
    tap(f"p:{sid}")
    assert store.action(db, "https://x/0") == "applied"
    short = [p for m, p in b.http.posts if m == "editMessageText"][-1]["text"]
    assert short.startswith("✅ подано ") and " · таблиця, рядок 19 · <a href=" in short
    tap(f"u:{sid}")
    tap(f"p:{sid}")  # changed my mind back: the package already exists
    tap(f"u:{sid}")
    tap(f"d:{sid}")
    tap(f"u:{sid}")
    assert calls == [("build", "https://x/0")]
    assert [c[0] for c in s.calls] == ["add", "undo", "add", "undo"] and s.calls[0][2]["company"] == "Acme"
    assert s.calls[0][2]["pkg"]["cv"] == "PL · бот"
    assert answers(b) == ["Збираю пакет, ~30 с", "Скасовано · прибрав з таблиці", "Пакет уже є, записую подачу",
                          "Скасовано · прибрав з таблиці", "Записав 👎", "Скасовано"]


def test_sheet_down_still_saves_and_says_so_in_the_card(db, monkeypatch):
    fake_package(monkeypatch)
    sid = store.mark_sent(db, "https://x/0", 7)
    b = bot()
    tg.handle(db, b, {"callback_query": {"id": "q", "data": f"p:{sid}", "from": {"id": CHAT},
                                         "message": card_msg()}}, FakeSheet(fail=True))
    assert store.action(db, "https://x/0") == "applied"
    assert " · 🔴 таблиця: RuntimeError · " in [p for m, p in b.http.posts if m == "editMessageText"][-1]["text"]
    press(db, b, f"u:{sid}")  # no sheet in .env
    assert answers(b)[-1] == "Скасовано · 🔴 таблиця не налаштована (.env)"


def fake_package(monkeypatch, gaps=((5, "Jira"),), fail=None, body="Dzień dobry,\n\n<treść>"):
    from jobbot import package
    calls = []

    def build(db, url, client):
        if fail:
            raise RuntimeError(fail)
        calls.append(("build", url))
        return {"pdf": b"%PDF", "filename": "Jan_Kowalski_CV_Acme.pdf", "problems": [], "lang": "pl",
                "note": "Dzień dobry, aplikowałem na Junior AI.", "subject": "Aplikacja: Junior AI, Jan Kowalski",
                "body": body, "gaps": list(gaps), "cost": 0.012}

    def rebuild(db, url):
        calls.append(("rebuild", url))
        return {"pdf": b"%PDF2", "filename": "Jan_Kowalski_CV_Acme.pdf", "problems": ["сторінок 2"], "body": body}
    monkeypatch.setattr(package, "build", build)
    monkeypatch.setattr(package, "rebuild", rebuild)
    return calls


def test_package_button_sends_cv_texts_and_gap_questions(db, monkeypatch):
    """Step 4 (owner decision 10.10): box -> PDF, connection note and cover letter, gap questions with 4 levels."""
    calls = fake_package(monkeypatch)
    b = bot()
    sid = store.mark_sent(db, "https://x/0", 7, meta={"company": "Acme"})
    press(db, b, f"p:{sid}")
    methods = [m for m, _ in b.http.posts]
    assert methods == ["answerCallbackQuery", "sendDocument", "sendMessage", "editMessageReplyMarkup"]
    assert calls == [("build", "https://x/0")]
    assert answers(b) == ["Збираю пакет, ~30 с"]
    doc = b.http.posts[1][1]  # 10.10: fits into 1024 - everything as one message (owner decision)
    assert doc["document"] == ("Jan_Kowalski_CV_Acme.pdf", b"%PDF") and doc["parse_mode"] == "HTML"
    assert doc["caption"].startswith("📦 <b>Acme</b> · CV PL")
    assert "<blockquote>Dzień dobry, aplikowałem na Junior AI.</blockquote>" in doc["caption"]  # the note as a quote
    assert "✉️ Тема: <b>Aplikacja: Junior AI, Jan Kowalski</b>" in doc["caption"]  # the subject in bold
    assert "$" not in doc["caption"]
    assert "<blockquote expandable>Dzień dobry,\n\n&lt;treść&gt;</blockquote>" in doc["caption"]
    texts = b.http.sent()
    assert "<b>Jira</b>" in texts[0]["text"]
    kb = texts[0]["reply_markup"]["inline_keyboard"]
    assert [[k["callback_data"] for k in row] for row in kb] == [["g:5:r", "g:5:b"], ["g:5:l", "g:5:n"]]
    # without a channel the package sits under the card - no 'open' button, only the applied undo
    kb = [p for m, p in b.http.posts if m == "editMessageReplyMarkup"][0]["reply_markup"]["inline_keyboard"]
    assert kb == [[{"text": "✅ подано · ↩️", "callback_data": f"u:{sid}"}]]


PKG = -1001234567890


def test_package_goes_to_channel_and_card_gets_a_link(db, monkeypatch):
    """11.10 (owner): the chat holds postings only; CV, texts and questions go to the channel, the card gets a link button to the package."""
    calls = fake_package(monkeypatch)
    b = tg.Bot("TOKEN", CHAT, FakeHttp(), pkg_chat=PKG)
    url = "https://x/0"
    sid = store.mark_sent(db, url, 7, meta={"company": "Acme", "title": "Junior AI"})
    store.save_package(db, url, {}, {})  # the real build writes it itself
    press(db, b, f"p:{sid}")
    doc = [p for m, p in b.http.posts if m == "sendDocument"][0]
    assert doc["chat_id"] == str(PKG) and 'href="https://x/0">Junior AI</a>' in doc["caption"]
    question = b.http.sent()[0]
    assert question["chat_id"] == PKG and "<b>Jira</b>" in question["text"]
    edit = [p for m, p in b.http.posts if m == "editMessageReplyMarkup"][0]
    assert edit["chat_id"] == CHAT and edit["message_id"] == 7
    assert edit["reply_markup"]["inline_keyboard"][1] == [{"text": "📂 відкрити пакет", "url": "https://t.me/c/1234567890/102"}]  # PDF id from FakeHttp
    # a gap answer is tapped in the channel: accepted, removed there, the new CV goes into the same channel message
    gid = store.add_gap(db, url, "Jira", "integrations")
    press(db, b, f"g:{gid}:r", chat=PKG, mid=55)
    assert [(p["chat_id"], p["message_id"]) for m, p in b.http.posts if m == "deleteMessage"] == [(PKG, 55)]
    media = [p for m, p in b.http.posts if m == "editMessageMedia"][0]
    assert media["chat_id"] == str(PKG) and calls[-1] == ("rebuild", url)
    # a foreign chat is still not allowed anything, even when a channel exists
    press(db, b, f"d:{sid}", chat=111)
    assert store.action(db, url) == "applied"


def test_applied_collapses_card_and_undo_restores_it_word_for_word(db, monkeypatch):
    """11.10 (owner): after applying the card is one line; undo restores the original together with its markup (entities)."""
    fake_package(monkeypatch)
    b = bot()
    url = "https://x/0"
    sid = store.mark_sent(db, url, 7, meta={"company": "Acme", "title": "Dev <R&D>"})
    card = {"message_id": 7, "chat": {"id": CHAT}, "text": "🟢 9/10 · Dev <R&D>\n🏢 Acme",
            "entities": [{"type": "bold", "offset": 3, "length": 4}]}
    tap = lambda data: tg.handle(db, b, {"callback_query": {"id": "q", "data": data, "from": {"id": CHAT},
                                                            "message": card}})
    tap(f"p:{sid}")
    short = [p for m, p in b.http.posts if m == "editMessageText"][-1]
    assert short["text"].startswith("✅ подано ") and "<b>Dev &lt;R&amp;D&gt;</b></a> · Acme" in short["text"]
    assert " · 🔴 таблиця не налаштована (.env) · " in short["text"]
    assert short["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"u:{sid}"
    tap(f"u:{sid}")
    back = [p for m, p in b.http.posts if m == "editMessageText"][-1]
    assert back["text"] == card["text"] and back["entities"] == card["entities"] and "parse_mode" not in back
    assert [k["callback_data"] for k in back["reply_markup"]["inline_keyboard"][0]] == [f"d:{sid}", f"p:{sid}"]


def test_long_letter_goes_separately_and_caption_fits_the_limit(db, monkeypatch):
    """10.10: caption 333 + letter 713 = 1076 > 1024 - the letter goes as a separate message."""
    fake_package(monkeypatch, gaps=(), body="Dzień dobry, " + "ą" * 900)
    b = bot()
    sid = store.mark_sent(db, "https://x/0", 7, meta={"company": "Acme"})
    press(db, b, f"p:{sid}")
    doc = b.http.posts[1][1]
    assert "expandable" not in doc["caption"] and tg.tg_len(doc["caption"]) <= tg.CAPTION_MAX
    assert b.http.sent()[0]["text"].startswith("✉️ Лист (тапни, щоб розгорнути):\n<blockquote expandable>")


def test_caption_length_counts_like_telegram():
    assert tg.tg_len("<b>ab</b>&amp;") == 3 and tg.tg_len("📦") == 2  # markup is not counted, an emoji = 2


def test_gap_answer_goes_to_bank_and_only_cv_levels_rebuild(db, monkeypatch):
    calls = fake_package(monkeypatch)
    b = bot()
    url = "https://x/0"
    store.save_package(db, url, {}, {})
    store.set_package_message(db, url, 42, "📦 <b>Acme</b> · CV PL")
    g1, g2 = store.add_gap(db, url, "Jira", "integrations"), store.add_gap(db, url, "Excel", "automation")
    press(db, b, f"g:{g1}:b", mid=101)
    press(db, b, f"g:{g2}:l", mid=102)
    press(db, b, "g:999:r")
    assert store.answers(db) == [("Jira", "basics", "integrations"), ("Excel", "learning", "automation")]
    assert calls == [("rebuild", url)]  # 📚 learning does not change the CV
    # 10.10: the question does not linger - removed, the answer as a popup
    assert [p["message_id"] for m, p in b.http.posts if m == "deleteMessage"] == [101, 102]
    assert answers(b) == ["Jira: 👌 пробував, знаю інтерфейс, у рядок «Основи»",
                          "Excel: 📚 вчу зараз, у learning, у CV не йде", "Не знайшов питання"]
    # the new CV goes into the same PDF message, not another one
    media = [p for m, p in b.http.posts if m == "editMessageMedia"][0]
    assert media["message_id"] == "42" and media["cv"] == ("Jan_Kowalski_CV_Acme.pdf", b"%PDF2")
    cap = json.loads(media["media"])["caption"]
    assert cap.startswith("📦 <b>Acme</b> · CV PL\n🔄 CV оновлено: + Jira\n⚠️ сторінок 2\n\n✉️ Лист")
    assert "<blockquote expandable>" in cap  # the letter is still in the caption because it fits
    assert store.package_message(db, url) == (42, "📦 <b>Acme</b> · CV PL\n🔄 CV оновлено: + Jira")
    assert not [m for m, _ in b.http.posts if m == "sendDocument"]


def test_package_failure_is_said_in_red(db, monkeypatch):
    fake_package(monkeypatch, fail="нема тексту вакансії в базі")
    b = bot()
    sid = store.mark_sent(db, "https://x/0", 7)
    s = FakeSheet()
    tg.handle(db, b, {"callback_query": {"id": "q", "data": f"p:{sid}", "from": {"id": CHAT},
                                         "message": card_msg()}}, s)
    assert b.http.sent()[-1]["text"] == "🔴 Пакет не зібрано: RuntimeError: нема тексту вакансії в базі"
    # 12.10 (owner): the row only after a finished package - the package failed, no application, the card stays as it was
    assert store.action(db, "https://x/0") is None and s.calls == []
    assert not [m for m, _ in b.http.posts if m.startswith("editMessage")]


def test_dislike_one_tap_with_reason(db):
    b = bot()
    sid = store.mark_sent(db, "https://x/0", 7)
    press(db, b, f"d:{sid}")
    row = db.execute("SELECT kind, reason FROM actions").fetchone()
    assert row == ("dislike", tg.DISLIKE)


@pytest.mark.parametrize("user,chat", [(111, CHAT), (CHAT, 111), (111, 111)])
def test_foreign_user_or_chat_changes_nothing(db, user, chat):
    """Requirement 12: chat_id allowlist."""
    b = bot()
    sid = store.mark_sent(db, "https://x/0", 7)
    press(db, b, f"p:{sid}", user=user, chat=chat)
    assert store.action(db, "https://x/0") is None
    assert [m for m, _ in b.http.posts] == ["answerCallbackQuery"]


def test_unknown_or_broken_callback_is_answered_not_crashed(db):
    b = bot()
    sid = store.mark_sent(db, "https://x/0", 7)
    press(db, b, "a:999")
    press(db, b, "zzz")
    press(db, b, f"a:{sid}")  # the check-mark button is gone since 12.10: an old button writes nothing
    assert db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0
    assert [m for m, _ in b.http.posts] == ["answerCallbackQuery"] * 3
