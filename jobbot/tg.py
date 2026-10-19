"""Step 5a (07.10): digest in Telegram and buttons.

Owner decisions 06-07.10: a header after EVERY scan, even an empty one (silence = the bot is down); a separate message
per posting, each arrives once; the evening scan is silent; thumbs-down in one tap ('wrong role / level'),
undo reverts a tap (tests and misclicks do not spoil the funnel and the thumbs-down metric). Since 12.10 the box button 'applying' = package
+ application + sheet row, no separate check mark. We answer only the chat_id from .env (requirement 12), site text is escaped (requirement 15)."""
import html
import json
import re
import sys
import time

import httpx

from . import config, rank, store
from .sheet import Sheet, shown_company

DISLIKE = "не та роль / рівень"
SILENT_FROM = 21  # hour in Warsaw: the evening digest is silent


def env(name: str) -> str | None:
    """One value from .env; the file is never printed whole."""
    path = rank.ROOT / ".env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.partition("=")[2].strip().strip('"') or None
    return None


class Bot:
    def __init__(self, token: str, chat_id: int, http=None, pkg_chat: int | None = None):
        self._url = f"https://api.telegram.org/bot{token}/"  # contains the token: never goes into logs or exceptions
        self.chat_id = chat_id
        # 11.10 (owner): packages (CV, texts, gaps) go to a separate channel, the chat holds postings only. No channel - as before
        self.pkg_chat = pkg_chat or chat_id
        self.http = http or httpx.Client(timeout=70)

    @classmethod
    def from_env(cls) -> "Bot":
        token, chat, pkg = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID"), env("TELEGRAM_PACKAGES_CHAT_ID")
        if not token or not chat:
            raise RuntimeError("у .env нема TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID")
        return cls(token, int(chat), pkg_chat=int(pkg) if pkg else None)

    def call(self, method: str, files=None, **params):
        if files:  # form: values as strings, true/false as in JSON
            data = {k: v if isinstance(v, str) else json.dumps(v) for k, v in params.items()}
            r = self.http.post(self._url + method, data=data, files=files)
        else:
            r = self.http.post(self._url + method, json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description')}")
        return data["result"]

    def send(self, text: str, silent: bool = False, keyboard=None, chat: int | None = None) -> dict:
        params = {"chat_id": chat or self.chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True, "disable_notification": silent}
        if keyboard:
            params["reply_markup"] = keyboard
        return self.call("sendMessage", **params)

    def send_document(self, data: bytes, filename: str, caption: str = "", chat: int | None = None) -> dict:
        return self.call("sendDocument", files={"document": (filename, data)}, chat_id=chat or self.chat_id,
                         caption=caption, parse_mode="HTML", disable_notification=True)


def e(s) -> str:
    return html.escape(str(s), quote=False)


def keyboard(sid: int, state: str | None, pkg: str | None = None) -> dict:
    if state == "applied":
        row = [{"text": "✅ подано · ↩️", "callback_data": f"u:{sid}"}]
    elif state == "dislike":
        row = [{"text": "👎 не те · ↩️", "callback_data": f"u:{sid}"}]
    else:
        row = [{"text": "👎 не те", "callback_data": f"d:{sid}"}, {"text": "📦 подаюсь", "callback_data": f"p:{sid}"}]
    return {"inline_keyboard": [row] + ([[{"text": "📂 відкрити пакет", "url": pkg}]] if pkg else [])}


def pkg_link(bot: "Bot", meta: dict) -> str | None:
    """Link to the package in the channel. A package in the same chat (before 11.10 or without a channel) sits below - no button needed."""
    p = meta.get("pkg")
    if not p or p["chat"] == bot.chat_id:
        return None
    return f"https://t.me/c/{str(p['chat']).removeprefix('-100')}/{p['msg']}"


def pkg_chat(bot: "Bot", meta: dict) -> int:
    """Where this posting's package lives: those built before the channel are in the chat."""
    return meta.get("pkg", {}).get("chat", bot.chat_id)


def collapsed(meta: dict, url: str, sheet_note: str = "") -> str:
    """Card after applying (owner 11.10): one line, so the postings chat does not grow from applied ones. 12.10: the sheet row
    or a red alert goes here too - the popup is already taken by 'Building the package'."""
    return (f"✅ подано {rank.now_warsaw():%d.%m}{e(sheet_note)} · <a href=\"{html.escape(url, quote=True)}\"><b>"
            f"{e(meta.get('title', 'вакансія'))}</b></a> · {e(shown_company(meta.get('company', ''), meta.get('source', '')))}")


# A gap in the bank (owner decision 10.10): 4 levels
GAP_LEVELS = {"r": "🔧 працюю регулярно", "b": "👌 пробував, знаю інтерфейс", "l": "📚 вчу зараз", "n": "❌ ніколи"}
GAP_WHERE = {"r": "у навички CV", "b": "у рядок «Основи»", "l": "у learning, у CV не йде", "n": "більше не питаю"}


def gap_keyboard(gid: int) -> dict:
    k = [{"text": t, "callback_data": f"g:{gid}:{c}"} for c, t in GAP_LEVELS.items()]
    return {"inline_keyboard": [k[:2], k[2:]]}


def problems(p: dict) -> str:
    return f"\n⚠️ {e(', '.join(p['problems']))}" if p["problems"] else ""


CAPTION_MAX = 1024  # file caption in the Bot API; counted in UTF-16 after markup parsing (an emoji = 2)


def tg_len(s: str) -> int:
    return len(html.unescape(re.sub(r"<[^>]+>", "", s)).encode("utf-16-le")) // 2


def with_letter(head: str, body: str) -> tuple[str, bool]:
    """One message when it fits (owner decision 10.10): the letter as a collapsed quote in the PDF caption; otherwise separately."""
    full = f"{head}\n\n✉️ Лист (тапни, щоб розгорнути):\n<blockquote expandable>{e(body)}</blockquote>"
    return (full, True) if tg_len(full) <= CAPTION_MAX else (head, False)


def send_letter(bot: "Bot", body: str, chat: int | None = None) -> None:
    bot.send(f"✉️ Лист (тапни, щоб розгорнути):\n<blockquote expandable>{e(body)}</blockquote>", silent=True, chat=chat)


def send_package(db, bot: "Bot", url: str, client=None) -> str | None:
    """Box button (owner decision 10.10): PDF with a caption (note and subject - tap to copy), the letter collapsed below it,
    gap questions disappear after an answer. Caption <= 1024 chars - hence the letter goes separately when long. Silent.
    Since 11.10 everything goes to the packages channel; returns the package link for the card button."""
    from . import package
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=rank.api_key())
    p = package.build(db, url, client)
    meta = store.sent_meta(db, url)
    long_note = " ⚠️ задовга, скороти" if len(p["note"]) > 200 else ""
    # 10.10 (owner): the note as a quote, the subject in bold; the cost goes to logs, not the caption (room for the letter).
    # 11.10: in the channel the package has no card next to it, so the posting title is a link
    head = (f"📦 <b>{e(meta.get('company', ''))}</b> · CV {p['lang'].upper()}\n"
            f"<a href=\"{html.escape(url, quote=True)}\">{e(meta.get('title', 'вакансія'))}</a>\n\n"
            f"🤝 Конект ({len(p['note'])}/200{long_note}):\n<blockquote>{e(p['note'])}</blockquote>\n"
            f"✉️ Тема: <b>{e(p['subject'])}</b>")
    print(f"пакет {meta.get('company', '')}: ${p['cost']:.3f}", file=sys.stderr, flush=True)
    caption, inside = with_letter(head + problems(p), p["body"])
    msg = bot.send_document(p["pdf"], p["filename"], caption, chat=bot.pkg_chat)
    store.set_package_message(db, url, msg["message_id"], head)
    store.update_meta(db, url, pkg={"chat": bot.pkg_chat, "msg": msg["message_id"],
                                    "cv": f"{p['lang'].upper()} · бот"})  # CV column: language · type (owner 12.10)
    if not inside:
        send_letter(bot, p["body"], chat=bot.pkg_chat)
    for gid, skill in p["gaps"]:
        bot.send(f"❓ Вакансія хоче <b>{e(skill)}</b>. Як у тебе з цим?", silent=True, keyboard=gap_keyboard(gid),
                 chat=bot.pkg_chat)
    return pkg_link(bot, store.sent_meta(db, url))


def answer_gap(db, bot: "Bot", q: dict, data: str) -> None:
    from . import cv, package
    gid, _, lvl = data.partition(":")
    row = store.answer_gap(db, int(gid), cv.LEVELS[lvl]) if gid.isdigit() and lvl in GAP_LEVELS else None
    if row is None:
        bot.call("answerCallbackQuery", callback_query_id=q["id"], text="Не знайшов питання")
        return
    url, skill = row
    # The question does not linger (owner 10.10): the answer as a popup, the message is removed
    bot.call("answerCallbackQuery", callback_query_id=q["id"], text=f"{skill}: {GAP_LEVELS[lvl]}, {GAP_WHERE[lvl]}")
    bot.call("deleteMessage", chat_id=q["message"]["chat"]["id"], message_id=q["message"]["message_id"])
    if lvl in ("r", "b"):
        chat = pkg_chat(bot, store.sent_meta(db, url))
        try:
            p = package.rebuild(db, url)
        except Exception as ex:
            bot.send(f"🔴 CV не перезібрано: {e(type(ex).__name__)}: {e(str(ex)[:200])}", chat=chat)
            return
        msg = store.package_message(db, url)
        head = (msg[1] if msg else "📦") + f"\n🔄 CV оновлено: + {e(skill)}"
        caption, inside = with_letter(head + problems(p), p["body"])
        if msg:  # a new file in the same message, not another one
            bot.call("editMessageMedia", files={"cv": (p["filename"], p["pdf"])}, chat_id=chat,
                     message_id=msg[0], media={"type": "document", "media": "attach://cv", "caption": caption,
                                               "parse_mode": "HTML"})
            store.set_package_message(db, url, msg[0], head)
            if with_letter(msg[1], p["body"])[1] and not inside:  # the letter was in the caption and no longer fits
                send_letter(bot, p["body"], chat=chat)
        else:
            bot.send_document(p["pdf"], p["filename"], caption, chat=chat)


MODES = {"remote": "віддалено", "hybrid": "гібрид", "office": "офіс"}
# Human-readable source name (owner 10.10)
SITES = {"pracuj": "pracuj.pl", "justjoin": "justjoin.it", "rocketjobs": "rocketjobs.pl", "theprotocol": "theprotocol.it",
         "bulldogjob": "bulldogjob.pl", "solidjobs": "solid.jobs", "praca": "praca.pl", "djinni": "djinni.co",
         "olx": "olx.pl", "dou": "dou.ua", "nofluffjobs": "nofluffjobs.com"}


def card(final: int, job, s: dict, marks: list[str]) -> str:
    """Visual 10.10 (owner decision): title = link, blocks separated by an empty line, green = 8+.
    The model extract (in English) exists only in scores since 10.10; older ones render without it."""
    where = "remote" if job.remote else ", ".join(job.cities[:3])
    days = int((time.time() - job.posted_at) // 86400)
    contract = f" · 📄 {e(s['contract'])}" if s.get("contract", "unknown") != "unknown" else ""
    lines = [f"{'🟢' if final >= 8 else '🟡'} <b>{final}/10</b> · "
             f"<a href=\"{html.escape(job.url, quote=True)}\"><b>{e(job.title)}</b></a>",
             f"🏢 {e(shown_company(job.company, job.source))} · 📍 {e(where)} · {e(SITES.get(job.source, job.source))}",
             f"💰 {e(job.salary or 'без вилки')}{contract}",
             " · ".join(([f"🏠 {MODES[job.mode]}"] if job.mode in MODES else [])
                        + [f"🕒 {f'{days} дн тому' if days else 'сьогодні'}"])]
    if s.get("why"):
        lines += ["", f"💬 {e(s['why'])}"]
    extract = [(icon, label, s.get(key, [])[:n], sep) for icon, label, key, n, sep in (
        ("🛠", "задачі", "tasks", 3, "; "), ("📋", "вимоги", "requirements", 5, "; "),
        ("🧰", "стек", "stack", 8, ", "), ("🎁", "пропонують", "offer", 3, "; "))]
    extract = [f"{icon} {label}: {e(sep.join(items))}" for icon, label, items, sep in extract if items]
    if extract:
        lines += [""] + extract
    extra = ([f"✔️ є: {e(', '.join(s['matched'][:5]))}"] if s.get("matched") else []) + [e(m) for m in marks] \
        + ([f"➕ бракує: {e(', '.join(s['missing'][:4]))}"] if s.get("missing") else [])
    if extra:
        lines += [""] + extra
    return "\n".join(lines)


def header(when, statuses, ranked: dict, fresh: int, stale=()) -> str:
    """One status line + red/yellow sources + a scoring note (balance). Visible even when there are no postings."""
    ok = sum(1 for *_, icon, _ in statuses if icon in ("✅", "⚪"))
    bad = [(icon, f"{src} · {q}: {note}") for src, q, icon, note in statuses if icon not in ("✅", "⚪")]
    top = "🔴" if any(i == "🔴" for i, _ in bad) or "🔴" in ranked["note"] else "✅"
    lines = [f"{top} <b>Скан {when:%H:%M}</b> · нових {config.DIGEST_MIN}+: <b>{fresh}</b>",
             f"📡 джерела {ok}/{len(statuses)} · 🤖 оцінено {ranked['scored']} (${ranked['cost']:.2f}) · "
             f"⏳ у черзі {ranked['waiting']}"]
    if ranked.get("waiting0"):
        lines.append(f"🟡 Познань/віддалено чекає стелі: {ranked['waiting0']}, час вмикати правило «група 0 вся»")
    if stale:  # sensor 19.10: a week of digests without a single reaction was not visible anywhere
        days = (when.timestamp() - min(ts for _, ts in stale)) / 86400
        lines.append(f"⏳ карток без 📦/👎 понад 2 дн: {len(stale)} (8+: {sum(s >= 8 for s, _ in stale)}), "
                     f"найстарша {days:.0f} дн")
    lines += [f"{icon} {e(text)}" for icon, text in bad[:6]]
    if len(bad) > 6:
        lines.append(f"… ще {len(bad) - 6}, усе у файлі скану")
    if ranked["note"]:
        lines.append(e(ranked["note"]))
    return "\n".join(lines)


def send_letters(db, bot: Bot, items: list[dict], more: int, silent: bool) -> None:
    """5b (owner decision 11.10): LinkedIn/Indeed from alert e-mails as one message, without scoring or buttons; shown ones go to sent
    so they do not repeat. Not delivered - nothing is marked, it comes with the next scan."""
    lines = ["📬 <b>З листів LinkedIn/Indeed</b> · без оцінки: сторінки цих сайтів читати не можна"]
    lines += [f"• <a href=\"{html.escape(it['url'], quote=True)}\">{e(it['title'])}</a> · {e(it['company'])} · "
              f"{e(it['place'])} · {it['site']}" for it in items]
    if more:
        lines.append(f"… ще {more}, прийдуть наступним сканом")
    msg = bot.send("\n".join(lines), silent=silent)
    for it in items:
        store.mark_sent(db, it["url"], msg["message_id"], meta={"title": it["title"], "company": it["company"],
                                                                "where": it["place"], "source": it["site"]})


def send_scan(db, bot: Bot, statuses, ranked: dict, marks: dict, when, letters=([], 0)) -> int:
    """Header, then new ones above the threshold, each once, the letters block at the end. Returns how many postings were sent."""
    fresh = [r for r in ranked["worthy"] if store.sent_id(db, r[1].url) is None][:config.DIGEST_TOP]
    paused = ranked["note"].startswith("⏸")
    silent = when.hour >= SILENT_FROM or paused  # pause: only a sign that the bot is alive
    bot.send(header(when, statuses, ranked, len(fresh), store.stale(db)), silent=silent)
    n = 0
    for final, job, s in fresh:
        where = ("remote" if job.remote else ", ".join(job.cities[:3])) + (f" · {MODES[job.mode]}" if job.mode in MODES else "")
        sid = store.mark_sent(db, job.url, meta={  # id for the button first; the data is for the applications sheet row (5b)
            "title": job.title, "company": job.company, "where": where, "source": SITES.get(job.source, job.source),
            "score": final, "missing": s.get("missing", [])})
        try:
            msg = bot.send(card(final, job, s, marks.get(job.url, [])), silent=silent, keyboard=keyboard(sid, None))
        except Exception:
            store.unmark_sent(db, sid)  # not delivered - it comes with the next scan
            raise
        store.set_message(db, sid, msg["message_id"])
        n += 1
    if letters[0] and not paused:
        send_letters(db, bot, *letters, silent=silent)
    return n


def to_sheet(sheet, op: str, url: str, meta: dict) -> str:
    """The tail of the popup after a tap (5b). The sheet failed - the application is still in the database, the reason is in the popup."""
    if sheet is None:
        return " · 🔴 таблиця не налаштована (.env)"
    try:
        if op == "add":
            n, new = sheet.append(url, meta, rank.now_warsaw().date())
            return f" · таблиця, рядок {n}" if new else f" · уже в таблиці, рядок {n}"
        return {"removed": " · прибрав з таблиці", "absent": ""}[sheet.remove(url)]
    except Exception as ex:
        print(f"таблиця: {type(ex).__name__}: {str(ex)[:150]}", file=sys.stderr, flush=True)
        return f" · 🔴 таблиця: {type(ex).__name__}"


def apply(db, bot: Bot, q: dict, msg: dict, sid: int, url: str, sheet) -> None:
    """Box button 'applying' (owner 11.10): package -> application -> sheet row -> the card collapses. The row only after a finished
    package (12.10): the package failed - no application, tap again. The package already exists (box after undo) - not rebuilt."""
    ready = "pkg" in store.sent_meta(db, url)
    # answer at once: building takes ~30 s, and Telegram does not wait long for answerCallbackQuery
    bot.call("answerCallbackQuery", callback_query_id=q["id"],
             text="Пакет уже є, записую подачу" if ready else "Збираю пакет, ~30 с")
    if not ready:
        try:
            send_package(db, bot, url)
        except Exception as ex:
            bot.send(f"🔴 Пакет не зібрано: {e(type(ex).__name__)}: {e(str(ex)[:200])}")
            print(f"пакет: {type(ex).__name__}: {str(ex)[:150]}", file=sys.stderr, flush=True)
            return
    meta = store.sent_meta(db, url)
    store.set_action(db, url, "applied")
    note = to_sheet(sheet, "add", url, meta)
    kb = keyboard(sid, "applied", pkg_link(bot, meta))
    if msg.get("text"):  # collapse; the original with markup is kept for undo, word for word
        if "full" not in meta:
            store.update_meta(db, url, full={"text": msg["text"], "entities": msg.get("entities", [])})
        bot.call("editMessageText", chat_id=bot.chat_id, message_id=msg["message_id"],
                 text=collapsed(meta, url, note), parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)
    else:
        bot.call("editMessageReplyMarkup", chat_id=bot.chat_id, message_id=msg["message_id"], reply_markup=kb)


def handle(db, bot: Bot, update: dict, sheet=None) -> None:
    """A button press. A foreign chat or user - nothing is written to the database (requirement 12)."""
    q = update.get("callback_query")
    if not q:
        return
    msg = q.get("message") or {}
    # Packages live in the channel since 11.10: gap questions are answered from there (from = owner, chat = channel)
    if q.get("from", {}).get("id") != bot.chat_id or msg.get("chat", {}).get("id") not in (bot.chat_id, bot.pkg_chat):
        bot.call("answerCallbackQuery", callback_query_id=q["id"])
        return
    kind, _, sid = (q.get("data") or "").partition(":")
    if kind == "g":
        return answer_gap(db, bot, q, sid)
    url = store.sent_url(db, int(sid)) if sid.isdigit() else None
    if url is None or kind not in ("d", "u", "p") or msg["chat"]["id"] != bot.chat_id:
        bot.call("answerCallbackQuery", callback_query_id=q["id"], text="Не знайшов вакансію")
        return
    if kind == "p":
        return apply(db, bot, q, msg, int(sid), url, sheet)
    meta = store.sent_meta(db, url)
    was = store.action(db, url)
    if kind == "d":
        store.set_action(db, url, "dislike", DISLIKE)
        state, note = "dislike", "Записав 👎"
    else:
        store.clear_action(db, url)
        state, note = None, "Скасовано" + (to_sheet(sheet, "undo", url, meta) if was == "applied" else "")
    kb = keyboard(int(sid), state, pkg_link(bot, meta))
    if was == "applied" and (full := meta.get("full")):
        bot.call("editMessageText", chat_id=bot.chat_id, message_id=msg["message_id"], text=full["text"],
                 entities=full["entities"], disable_web_page_preview=True, reply_markup=kb)
    else:
        bot.call("editMessageReplyMarkup", chat_id=bot.chat_id, message_id=msg["message_id"], reply_markup=kb)
    bot.call("answerCallbackQuery", callback_query_id=q["id"], text=note)


def poll(db, bot: Bot, stop=None) -> None:
    """Long polling for buttons. Logs to stderr: stdout during a scan is written to the scan file."""
    sheet, offset = Sheet.from_env(env), None
    while not (stop and stop.is_set()):
        try:
            updates = bot.call("getUpdates", offset=offset, timeout=50, allowed_updates=["callback_query"])
        except Exception as ex:
            print(f"getUpdates: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr, flush=True)
            time.sleep(10)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                handle(db, bot, u, sheet)
            except Exception as ex:  # one button does not bring polling down
                print(f"кнопка: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr, flush=True)


if __name__ == "__main__":  # buttons only, no schedule: a test from a laptop
    poll(store.connect(), Bot.from_env())
