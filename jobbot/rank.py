"""Step 3 (03.10): what goes to the model and model scoring against facts.yaml.

Owner decision 03.10: everything deterministic is done in code: a title blacklist, 'heavy' warnings (experience 3+,
senior without a number, a third language) as a separate list without the model, office in another city is a warning with the same bar.
The model scores only how the posting's tasks match the facts; code takes 1 point off for each soft warning (decision 28.09).
Programming languages are not rejected: an unfamiliar stack is a small minus for junior/mid, the main mismatch for senior.
Synchronous with prompt caching, a daily cap (freshest first), digest: top 10 above the threshold."""
import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import config
from .job import Job

ROOT = Path(__file__).resolve().parent.parent
WARSAW = ZoneInfo("Europe/Warsaw")
# One-off backfill (owner decision 08.10): a posting scored later at 8.5/10 was seen from 01.10, but the tail of group 0 never reached the model.
# File exists -> this scan scores all of group 0 up to 30 days over the cap and removes the file
BACKLOG_ONCE = ROOT / "data" / "backlog-once"
# Pause (owner decision 10.10): while per-posting CVs were being built, the scan only collects - no model, no digest
PAUSED = ROOT / "data" / "paused"


def paused_until(now: datetime) -> str | None:
    """None = no pause. Empty file = pause without an end. A date in the file ('2026-10-14 22:00', Warsaw) - pause until then;
    11.10 (owner): when the time comes the file is removed and group 0 is backfilled once, so nothing from the pause is lost."""
    if not PAUSED.exists():
        return None
    until = PAUSED.read_text(encoding="utf-8").strip()
    if until and now >= datetime.fromisoformat(until).replace(tzinfo=WARSAW):
        PAUSED.unlink()
        BACKLOG_ONCE.touch()
        return None
    return until or "без строку"

# Title blacklist (owner decision 03.10): DevOps/SRE/cloud/security/networks, SAP/ERP/hardware/non-IT.
# Programming languages and QA are deliberately not here.
DROP_TITLE = re.compile(
    r"\b(devops|devsecops|sre|site reliability|cloud (engineer|architect)|platform engineer|kubernetes|"
    r"security|cyber\w*|cyberbezpiecze\w*|soc analyst|pentest\w*|network engineer|administrator sieci|sieci|"
    r"sap|erp|dynamics( 365)?|salesforce developer|embedded|fpga|hardware|elektronik\w*|"
    r"monter\w*|instalator\w*|handlowiec|przedstawiciel handlowy|sales (representative|executive|manager)|"
    r"account executive|key account|nauczyciel\w*|teacher|lektor\w*)\b", re.I)
# A different profession from the title (owner decision 07.10): 66 of 160 model scores were 1-2, almost all visible from the title.
# We cut HR/recruiting, accounting/finance/law, design/video, marketing, B2B sales, physical work.
# Programming languages are NOT cut, neither is UX/UI (part of the owner's studies). Measured on the 07.10 22:18 scan: ~310 titles, not one scored 5+.
# Word boundaries on purpose: 'radca' sits inside 'Doradca', 'rekrutacja zdalna' is a hiring process, 'magazyn' also appears in process roles.
DROP_ROLE = re.compile(
    r"\b(recruiter\w*|rekruter\w*|ds\. rekrutacji|talent acquisition|sourcer|kadr\w*|payroll|płac\w*|"
    r"hr business partner|hr|"
    r"księgow\w*|ksiegow\w*|accountant|accounting|controlling\w*|kontroler\w* finans\w*|credit control|windykac\w*|"
    r"podatk\w*|tax|prawnik\w*|aplikant\w*|lawyer|legal counsel|radca|"
    r"motion design\w*|graphic design\w*|grafik\w*|game designer|projektant\w* graficzn\w*|video\w*|montażyst\w*|"
    r"animator\w*|illustrator|ilustrator\w*|creative producer|"
    r"media buy\w*|performance market\w*|seo|smm|social media|copywriter\w*|content creator|google ads|ppc|"
    r"marketing\w*|marketingow\w*|brand manager|user acquisition|"
    r"business development|bdr|sdr|telemarket\w*|sprzedawc\w*|account manager|doradc\w* handlow\w*|inside sales|"
    r"specjalist\w* ds\. sprzedaży|"
    r"magazynier\w*|kierowc\w*|driver|wózk\w*|konserwator\w*|technik\w* (obsługi )?(budynk\w*|obiektu)|spawacz\w*|"
    r"operator produkcji|pracownik produkcji|mechanik\w*|ślusarz\w*|sprząta\w*|kontroler\w* wagow\w*|elektryk\w*|"
    r"kucharz\w*|kelner\w*|recepcj\w*)\b|\bpracowni\w*\b.{0,25}\bmagazyn\w*", re.I)
# Our field in the title rescues from DROP_ROLE: 'Marketing Automation', 'Analityk HR', 'ds. procesow HR'
RESCUE_ROLE = re.compile(r"automat\w*|python|n8n|\brpa\b|integra\w*|\bdata\b|danych|analityk\w*|analyst|\bapi\b|"
                         r"proces\w*|process\w*|developer|programist\w*", re.I)
_OFFICE = re.compile(r"stacjonarn\w*|on-?site|w biurze|office-based|full[- ]time in (the )?office", re.I)
_FLEX = re.compile(r"hybryd\w*|hybrid|zdaln\w*|remote", re.I)
# 'Nie szukamy... osob zainteresowanych wylacznie praca zdalna' (a posting on 06.10) means office, not hybrid
_NEG = re.compile(r"\b(nie|not|no|bez|brak)\b", re.I)

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "why": {"type": "string"},
        "matched": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
        # Extract for the card (owner decision 10.10): after the score so it does not shift it; in English
        "tasks": {"type": "array", "items": {"type": "string"}},
        "requirements": {"type": "array", "items": {"type": "string"}},
        "stack": {"type": "array", "items": {"type": "string"}},
        "offer": {"type": "array", "items": {"type": "string"}},
        "contract": {"type": "string", "enum": ["UoP", "B2B", "UoP/B2B", "zlecenie", "other", "unknown"]},
    },
    "required": ["score", "why", "matched", "missing", "tasks", "requirements", "stack", "offer", "contract"],
    "additionalProperties": False,
}

RUBRIC = """Ти оцінюєш, наскільки вакансія підходить кандидатові, за його фактами нижче. Відповідь — JSON за схемою.

score — ціле 1-10: наскільки справжні задачі й вимоги вакансії збігаються з тим, що кандидат реально робив
(facts, skills з evidence). Рахуй суть роботи, а не збіг слів: «Python» у вакансії DevOps — не збіг.
- 8-10: основні задачі — те, що він уже робить (автоматизація, інтеграції API, боти, Python-скрипти, n8n,
  підтримка з автоматизацією, дані з SQL).
- 5-7: роль у його напрямку, але частина вимог нова; або junior/mid з мовою чи інструментом, яких він не знає
  (це можна вивчити, невеликий мінус).
- 1-4: інша професія, або основний стек йому чужий на рівні вище junior.
Напрямки, які йому цікаві: automation / AI automation, Python developer, tech support / helpdesk / customer success
з автоматизацією, integration / ops, дані / BI / контролінг з SQL, маркетинг з AI чи Google Sheets. Викладання — ні.
Стаж, мови спілкування й режим роботи вже перевірив код — не знижуй за них бал.
learning — те, що він лише вчить: це не досвід, але й не мінус для junior.
level: basics — знає базу і робив з AI-агентом, вручну ще вчить: де це головний інструмент ролі, збіг частковий.

why — одне речення українською, ≤200 символів: чому такий бал. Звертайся до кандидата на «ти»
(«це те, що ти вже робиш», «тобі бракує»), не «він» і не «кандидат»: картку читає він сам.
matched — навички кандидата, які прямо потрібні вакансії, назвами англійською, не id фактів (до 5).
missing — обов'язкові вимоги вакансії, яких у фактах нема (до 5, коротко, англійською).

Далі витяг з тексту вакансії для картки: англійською, короткими фразами, лише те, що в тексті є.
Чого в тексті нема — порожній список; не додумуй.
tasks — головні обов'язки (Zakres obowiązków / Responsibilities), до 3, кожен ≤60 символів.
requirements — обов'язкові вимоги (Wymagania / Requirements): досвід, освіта, мови, до 5, кожна ≤60 символів.
stack — технології й інструменти, названі у вакансії, як написано (n8n, PostgreSQL, BaseLinker), до 8.
offer — що пропонують, крім грошей (Oferujemy / We offer), до 3, кожне ≤50 символів.
contract — тип договору: UoP (umowa o pracę), B2B, UoP/B2B (на вибір), zlecenie, other, unknown (не сказано).

Факти кандидата (YAML):
"""


def facts_text() -> str:
    """The bank without contacts and CV parts (10.10 bank = CV v4: markup, PL translations, summary variants are not needed
    for scoring). 'Basics' skills with level basics: knows the basics, has done it with AI."""
    f = yaml.safe_load((ROOT / "facts.yaml").read_text(encoding="utf-8"))
    plain = lambda s: html.unescape(re.sub(r"</?b>", "", s))
    view = {"languages": f["languages"],
            "roles": [{"id": r["id"], "en": plain(r["en"]), **({"dates": r["dates"]["en"]} if "dates" in r else {})}
                      for r in f["roles"]],
            "facts": [{k: (plain(v) if k == "en" else v) for k, v in x.items() if k != "pl"} for x in f["facts"]],
            "skills": {cat: [{"name": plain(i["name"]), "evidence": i["evidence"], **({"level": "basics"}
                                                                                     if i.get("level") else {})}
                             for i in v["items"]] for cat, v in f["skills"].items()},
            "learning": f["learning"]}
    return yaml.safe_dump(view, allow_unicode=True, sort_keys=False)


def office_mark(job: Job, text: str) -> str | None:
    """Office in another city: a mark only, the bar is the same (owner decision 03.10).
    The site's mode field outweighs the text; the text is used only when the field is missing."""
    if job.remote or job.mode in ("remote", "hybrid") or _poznan(job) or not job.cities:
        return None
    if job.mode == "office" or (_OFFICE.search(text) and not _flex(text)):
        return f"⚠️ офіс: {', '.join(job.cities[:2])}"
    return None


def _poznan(job: Job) -> bool:
    return any("pozna" in c.lower() for c in job.cities)


def _flex(text: str) -> bool:
    """Hybrid or remote in a sentence without negation."""
    return any(_FLEX.search(s) and not _NEG.search(s) for s in re.split(r"[.!?\n]+", text))


def group(job: Job, marks: list[str]) -> int:
    """Queue order to the model (owner decision 06.10): 0 - no warnings and reachable (Poznan, remote);
    1 - the rest (soft warnings, hybrid or unknown mode in another city); 2 - office in another city."""
    if any(m.startswith("⚠️ офіс") for m in marks):
        return 2
    # 19.10: + Warsaw hybrid (owner priorities; two Warsaw-hybrid postings later scored 9 and 8 never got past the cap in group 1)
    warsaw_hybrid = job.mode == "hybrid" and any("warsz" in c.lower() for c in job.cities)
    if (_poznan(job) or job.remote or job.mode == "remote" or warsaw_hybrid) and not any(m.startswith("⚠️") for m in marks):
        return 0
    return 1


def heavy(marks: list[str]) -> str | None:
    """Reason for a 'heavy' warning or None. Experience 3+, senior without a number, a third language (owner decision 03.10), money (06.10)."""
    for m in marks:
        if (y := re.match(r"⚠️ стаж (\d+)\+", m)) and int(y.group(1)) >= 3:
            return m
        if m.startswith(("⚠️ senior", "⚠️ мова", "⚠️ гроші")):
            return m
    return None


def route(job: Job, text: str, marks: list[str]) -> tuple[str, str]:
    """(where, why): drop / low / notext / model."""
    if m := DROP_TITLE.search(job.title):
        return "drop", m.group(0)
    if (m := DROP_ROLE.search(job.title)) and not RESCUE_ROLE.search(job.title):
        return "drop", m.group(0)
    if why := heavy(marks):
        return "low", why
    if not text:
        return "notext", ""
    return "model", ""


def penalty(marks: list[str]) -> int:
    """Minus 1 for every soft warning left after the sieve (English B2, experience 2, office)."""
    return sum(1 for m in marks if m.startswith("⚠️"))


def score(client, model: str, job: Job, text: str, facts: str) -> tuple[dict, dict]:
    """Model scoring. The system part (rubric + facts) is cached, the posting is not."""
    r = client.messages.create(
        model=model,
        max_tokens=4096,  # 19.10: Haiku 5.5 thinks adaptively, with 1024 tokens 30 of 85 failed (stop_reason max_tokens)
        system=[{"type": "text", "text": RUBRIC + facts, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"Вакансія: {job.title} · {job.company} · {job.source}\n\n{text}"}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if r.stop_reason != "end_turn":
        raise RuntimeError(f"stop_reason {r.stop_reason}")
    data = json.loads(next(b.text for b in r.content if b.type == "text"))
    data["score"] = max(1, min(10, int(data["score"])))
    u = r.usage
    usage = {"in": u.input_tokens, "out": u.output_tokens,
             "cache_read": u.cache_read_input_tokens or 0, "cache_write": u.cache_creation_input_tokens or 0}
    return data, usage


def cost(model: str, usage: dict) -> float:
    """$ per call at the 25.09.2026 price list; cache: write 1.25x, read 0.1x of the input price."""
    pin, pout = config.PRICES[model]
    return (usage["in"] * pin + usage["cache_write"] * pin * 1.25 + usage["cache_read"] * pin * 0.1
            + usage["out"] * pout) / 1e6


def api_key() -> str | None:
    """The key from .env as one line; the file is never printed whole."""
    env = ROOT / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.partition("=")[2].strip().strip('"') or None
    return None


def now_warsaw() -> datetime:
    return datetime.now(WARSAW)


def budget(db, now: datetime) -> int:
    """How many more to score now. The day is Warsaw time (the server lives in UTC): the midday scan takes up to half of the cap,
    the evening one fills up to the full cap, so a missed midday scan does not eat half of the day (owner decision 07.10).
    A rolling 24 h window gave 0 at 12:11 and all 40 at 22:18."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    (n,) = db.execute("SELECT COUNT(*) FROM scores WHERE ts >= ?", (midnight,)).fetchone()
    cap = config.SCORE_CAP // 2 if now.hour < config.EVENING_FROM else config.SCORE_CAP
    return max(0, cap - n)


def step(db, jobs: list[Job], texts: dict, marks: dict, client=None, now: datetime | None = None) -> dict:
    """Sieve -> score new ones (up to the daily cap, freshest first; jobs are already sorted) -> digest.
    client=None: created from the .env key; no key - no scoring, the rest of the report still works."""
    from collections import Counter
    from . import store
    routes = {j.url: route(j, texts[j.url][0], marks[j.url]) for j in jobs}
    out = {"routes": Counter(r for r, _ in routes.values()), "scored": 0, "errors": 0, "cost": 0.0, "waiting": 0,
           "note": "", "old": 0, "no_credit": []}
    todo = [j for j in jobs if routes[j.url][0] == "model" and store.score_row(db, j.url) is None]
    pause = paused_until(now or now_warsaw())  # before backlog: the pause is over -> this same scan backfills group 0
    paused = pause is not None
    backlog = BACKLOG_ONCE.exists()
    cutoff = time.time() - (config.WINDOW_DAYS if backlog else config.SCORE_MAX_DAYS) * 86400
    out["old"] = sum(1 for j in todo if j.posted_at < cutoff)
    # sort is stable: inside a group the 'freshest first' order stays
    todo = sorted((j for j in todo if j.posted_at >= cutoff), key=lambda j: group(j, marks[j.url]))
    left = 0 if paused else budget(db, now or now_warsaw())
    if backlog and not paused:  # group 0 comes first, so todo[:left] = all of it + the normal cap
        left += sum(1 for j in todo if group(j, marks[j.url]) == 0)
        out["note"] = "разова дооцінка групи 0 понад стелю"
    out["waiting"] = max(0, len(todo) - left)
    # Measured 11.10: group 0 is ~12-15 per weekday, comes first and fits into the cap entirely. Hence a sensor, not an 'over
    # the cap' rule (owner decision 11.10): if it does not fit, the digest header shows it
    out["waiting0"] = 0 if paused else max(0, sum(1 for j in todo if group(j, marks[j.url]) == 0) - left)
    if todo and left:
        if client is None:
            key = api_key()
            if not key:
                out["note"] = "🟡 ключа Anthropic у .env нема, оцінки нема"
            else:
                import anthropic
                client = anthropic.Anthropic(api_key=key)
        if client is not None:
            facts = facts_text()
            for j in todo[:left]:
                try:
                    data, usage = score(client, config.SCORE_MODEL, j, texts[j.url][0], facts)
                except Exception as e:  # one posting does not bring the scan down; the error is visible in the report
                    out["errors"] += 1
                    if "credit balance" in str(e).lower():  # the remaining 39 would fail the same way - do not hammer the API
                        out["note"] = "🔴 баланс API скінчився, оцінки нема: поповнити console.anthropic.com"
                        out["no_credit"] = [j for j in todo if group(j, marks[j.url]) == 0][:config.NO_CREDIT_TOP]
                        break
                    out["note"] = f"🟡 помилка оцінки: {type(e).__name__}: {str(e)[:100]}"
                    continue
                c = cost(config.SCORE_MODEL, usage)
                store.save_score(db, j.url, config.SCORE_MODEL, data, c)
                out["scored"] += 1
                out["cost"] += c
    if backlog and not paused:
        BACKLOG_ONCE.unlink(missing_ok=True)
    rated = []
    for j in jobs:
        if routes[j.url][0] == "model" and (s := store.score_row(db, j.url)):
            rated.append((s["score"] - penalty(marks[j.url]), j, s))
    rated.sort(key=lambda r: -r[0])
    # Everything above the threshold: Telegram drops already-sent ones BEFORE the top-10 cut, otherwise new ones past the top ten would never arrive
    out["worthy"] = [] if paused else [
        r for r in rated if r[0] >= config.DIGEST_MIN_BY_MODEL.get(r[2].get("model"), config.DIGEST_MIN)]
    out["digest"] = out["worthy"][:config.DIGEST_TOP]
    if paused:
        out["note"] = f"⏸ пауза ({pause}): скан лише збирає, модель і дайджест вимкнено (data/paused)"
    out["low"] = [(j, routes[j.url][1]) for j in jobs if routes[j.url][0] == "low"]
    return out
