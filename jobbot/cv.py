"""Step 4 (owner decision 10.10): a package for one posting, built from the facts bank. The model only CHOOSES from the bank's lists (summary
variant, 5 skills for the first line, order of facts and skill lines, 'Basics'); code renders and lets through only what
exists in the bank (red line 19.09). What the posting wants but the bank lacks is a gap: a question to the owner in Telegram,
the answer goes to the skill_answers table and into the next CV. The bank without tailoring (default_choice) = CV v4 word for word."""
import html
import json
import re

import yaml

from . import config, rank

BANK = rank.ROOT / "facts.yaml"
ROLES = ("role-freelance", "role-media", "role-ads")
LEVELS = {"r": "regular", "b": "basics", "l": "learning", "n": "never"}
NOTE_MAX = 200

CSS = """  @page { size: A4; margin: 13mm 16mm; }
  * { box-sizing: border-box; }
  body { font-family: Arial, Helvetica, "Liberation Sans", sans-serif; font-size: 9.6pt; line-height: 1.3; color: #1a1a1a; margin: 0; }
  h1 { font-size: 19pt; margin: 0 0 1px; letter-spacing: 0.5px; }
  .name { font-size: 12.5pt; margin: 0 0 3px; }
  .contact { font-size: 9.3pt; margin: 0 0 6px; }
  .contact a { color: #1a1a1a; }
  h2 { font-size: 9.5pt; letter-spacing: 3px; margin: 9px 0 3px; padding-bottom: 2px; border-bottom: 1.5px solid #1a1a1a; }
  p { margin: 0 0 4px; }
  ul { margin: 1px 0 3px; padding-left: 15px; page-break-inside: avoid; }
  li { margin: 0 0 2px; }
  .job { display: flex; justify-content: space-between; margin-top: 6px; page-break-after: avoid; }
  .job .title { font-weight: bold; }
  .job .dates { color: #666; }
  .skilline { margin: 0 0 3px; }
  .rodo { font-size: 7.5pt; color: #999; margin-top: 7px; }"""

LETTER = {
    "pl": ("Aplikacja: {title}, Jan Kowalski",
           "Dzień dobry,\n\nnazywam się Jan Kowalski. Zobaczyłem ogłoszenie na stanowisko {title} na {site} i właśnie "
           "złożyłem aplikację przez {site}. Piszę bezpośrednio, bo ta rola naprawdę mnie zainteresowała.\n\n"
           "Buduję automatyzacje i systemy AI działające produkcyjnie u płacących klientów. Najbliżej Waszych wymagań: "
           "{tech}: {sentence}\n\nJestem dostępny w pełnym wymiarze godzin. CV w załączniku, chętnie opowiem więcej "
           "na rozmowie.\n\nZ poważaniem,\nJan Kowalski\n+48 000 000 000 · linkedin.com/in/jan-kowalski"),
    "en": ("Application: {title}, Jan Kowalski",
           "Hello,\n\nI'm Jan Kowalski. I saw the {title} opening on {site} and just applied through {site}. "
           "I'm writing directly because this role genuinely caught my attention.\n\nI build automation and AI systems "
           "that run in production for paying clients. The closest match to your requirements: {tech}: {sentence}\n\n"
           "I'm available full-time. My CV is attached, and I'd be glad to tell you more on a call.\n\n"
           "Best regards,\nJan Kowalski\n+48 000 000 000 · linkedin.com/in/jan-kowalski"),
}


def load(answers: list[tuple] = ()) -> dict:
    """Bank + answers to gaps (name, level, category). regular -> into the category line, basics -> 'Basics'."""
    b = yaml.safe_load(BANK.read_text(encoding="utf-8"))
    for name, level, cat in answers:
        if level == "learning":
            b["learning"].append(name)
        elif level == "never":
            b.setdefault("never", []).append(name)
        else:
            cat = "basics" if level == "basics" else (cat if cat in b["skills"] and cat != "basics" else "automation")
            b["skills"][cat]["items"].append({"name": html.escape(name, quote=False), "evidence": ["owner answer"],
                                              **({"level": "basics"} if level == "basics" else {})})
    return b


def plain(s: str) -> str:
    return html.unescape(re.sub(r"</?b>", "", s))


def known(b: dict) -> set[str]:
    """Everything the bank already has an answer for: skills (name, short, Polish), learning, never - lowercase."""
    names = {plain(v).lower() for items in b["skills"].values() for it in items["items"]
             for v in (it["name"], it.get("short"), it.get("pl")) if v}
    return names | {x.lower() for x in b["learning"]} | {x.lower() for x in b.get("never", [])}


def summaries(b: dict) -> list[dict]:
    return [s for s in b["summaries"] if s.get("approved", True)]


def default_choice(b: dict, lang: str) -> dict:
    """No tailoring: CV v4."""
    return {"lang": lang, "summary": "automation", "headline": b["cv"]["headline_default"], "priority": [],
            "skill_lines": [c for c in b["skills"] if c != "basics"],
            "basics": [plain(i["name"]) for i in b["skills"]["basics"]["items"] if not i.get("hidden")]}


def validate(b: dict, c: dict) -> dict:
    """Only what is in the bank; anything missing falls back to the default. The red line is held here, not in the prompt."""
    d = default_choice(b, c.get("lang") if c.get("lang") in ("pl", "en") else "pl")
    ok_sum = {s["id"] for s in summaries(b)}
    regular = {plain(it.get("short") or it["name"]): it for cat, v in b["skills"].items() if cat != "basics"
               for it in v["items"]}
    head = [h for h in dict.fromkeys(c.get("headline", [])) if h in regular][:5]
    head += [h for h in d["headline"] if h not in head][:5 - len(head)]
    facts = {f["id"] for f in b["facts"]}
    lines = [x for x in dict.fromkeys(c.get("skill_lines", [])) if x in d["skill_lines"]]
    asked = [x for x in dict.fromkeys(c.get("basics", [])) if x in d["basics"]]
    return {"lang": d["lang"], "summary": c.get("summary") if c.get("summary") in ok_sum else d["summary"],
            "headline": head, "priority": [p for p in c.get("priority", []) if p in facts],
            "skill_lines": lines + [x for x in d["skill_lines"] if x not in lines],
            # 'Basics' always all of them (owner decision 10.10: never removed from the CV), the ones the posting asks for first
            "basics": asked + [x for x in d["basics"] if x not in asked]}


def _skill(it: dict, lang: str, short: bool = False) -> str:
    return (it.get("short") if short else None) or (it.get("pl") if lang == "pl" else None) or it["name"]


FONTS = (9.6, 9.3, 9.0)  # 10.10: 2 pages -> one font step down (owner decision), 9.6 = CV v4


def render(b: dict, c: dict, font: float = FONTS[0]) -> str:
    lang, p = c["lang"], b["person"]
    head = b["cv"]["headings"][lang]
    s = next(x for x in b["summaries"] if x["id"] == c["summary"])
    by_short = {plain(it.get("short") or it["name"]): it for cat, v in b["skills"].items() if cat != "basics"
                for it in v["items"]}
    out = ['<!DOCTYPE html>', f'<html lang="{lang}">', '<head>', '<meta charset="UTF-8">',
           '<title>Jan Kowalski · Automation Developer</title>', '<style>',
           CSS.replace("font-size: 9.6pt", f"font-size: {font}pt"), '</style>', '</head>', '<body>', '',
           f'<h1>{b["cv"]["title"]}</h1>', f'<p class="name">{p["name"]}</p>',
           f'<p class="contact">{p["location"][lang]} · <a href="mailto:{p["email"]}">{p["email"]}</a> · '
           f'<a href="{p["links"]["linkedin"]}">LinkedIn</a> · <a href="{p["links"]["github"]}">GitHub</a> · '
           f'<a href="{p["links"]["site"]}">{p["links"]["site"].split("//")[1]}</a></p>', '',
           f'<h2>{head["summary"]}</h2>',
           f'<p>{s["lead"][lang]}: <b>{", ".join(_skill(by_short[h], lang, True) for h in c["headline"])}</b>. '
           f'{s[lang]} {b["cv"]["tail"][lang]}</p>', '', f'<h2>{head["experience"]}</h2>']
    rank_of = {f: i for i, f in enumerate(c["priority"])}
    for role in (r for r in b["roles"] if r["id"] in ROLES):
        facts = [f for f in b["facts"] if f.get("role") == role["id"]]
        facts.sort(key=lambda f: rank_of.get(f["id"], len(rank_of)))  # stable: the rest in v4 order
        out += ['', f'<div class="job"><span class="title">{role[lang]}</span><span class="dates">{role["dates"][lang]}'
                    f'</span></div>', '<ul>'] + [f'<li>{f[lang]}</li>' for f in facts[:3]] + ['</ul>']
    earlier = next(r for r in b["roles"] if r["id"] == "role-earlier")
    out += ['', f'<p style="margin-top:6px;"><b>{b["cv"]["earlier"][lang]}:</b> {earlier[lang]}</p>', '',
            f'<h2>{head["skills"]}</h2>']
    for cat in c["skill_lines"]:
        items = [_skill(it, lang) for it in b["skills"][cat]["items"] if not it.get("hidden")]
        out.append(f'<p class="skilline"><b>{b["skills"][cat]["label"][lang]}:</b> {", ".join(items)}</p>')
    by_name = {plain(it["name"]): it for it in b["skills"]["basics"]["items"] if not it.get("hidden")}
    basics = [_skill(by_name[x], lang) for x in c["basics"] if x in by_name]  # in the order of the choice
    if basics:
        out.append(f'<p class="skilline"><b>{b["cv"]["basics_label"][lang]}:</b> {", ".join(basics)}</p>')
    out += ['', f'<h2>{head["education"]}</h2>', f'<div class="job"><span class="title">{p["education"][lang]}</span></div>',
            '', f'<h2>{head["languages"]}</h2>', f'<p>{b["cv"]["languages_line"][lang]}</p>', '']
    if lang == "pl":
        out += [f'<p class="rodo">{b["cv"]["rodo"]}</p>', '']
    return "\n".join(out + ['</body>', '</html>', ''])


def text_of(page_html: str) -> str:
    """Page text without tags and styles, whitespace collapsed: this is what we compare with CV v4 and the PDF."""
    body = re.sub(r"</?(b|a)\b[^>]*>", "", page_html.split("<body>", 1)[1])  # inline tags without a space
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())


# --- model

SCHEMA = {
    "type": "object",
    "properties": {
        "lang": {"type": "string", "enum": ["pl", "en"]},
        "summary": {"type": "string"},
        "headline": {"type": "array", "items": {"type": "string"}},
        "priority": {"type": "array", "items": {"type": "string"}},
        "skill_lines": {"type": "array", "items": {"type": "string"}},
        "basics": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "object", "properties": {
            "skill": {"type": "string"}, "category": {"type": "string"}},
            "required": ["skill", "category"], "additionalProperties": False}},
        "note": {"type": "string"},
        "tech": {"type": "string"},
        "sentence": {"type": "string"},
        "fact": {"type": "string"},
    },
    "required": ["lang", "summary", "headline", "priority", "skill_lines", "basics", "gaps", "note", "tech", "sentence",
                 "fact"],
    "additionalProperties": False,
}

RUBRIC = """Ти підбираєш CV кандидата під вакансію з ГОТОВОГО банку нижче. У CV ти нічого не пишеш сам: лише обираєш
зі списків банку, назви копіюєш точно. Відповідь — JSON за схемою.

lang — мова оголошення: pl, якщо воно польською; en для англійської та інших.
summary — id варіанту з summaries, найближчого до суті ролі (поле when каже, коли який).
headline — рівно 5 навичок для першого рядка, найважливіші для цієї вакансії, точними назвами зі списку headline_names.
priority — id фактів від найрелевантнішого для вакансії; код поставить їх першими у своїй ролі.
skill_lines — id категорій зі skill_lines, найрелевантніша перша, усі.
basics — назви зі списку basics, які вакансія прямо просить; не просить — порожньо.
gaps — до 3 обов'язкових вимог-навичок (інструмент, технологія, мова програмування), яких нема ні в skills, ні в
basics, ні в learning, ні в never. skill — коротка назва, як у вакансії (Excel, Jira, Power Automate). category — id
категорії зі skill_lines, куди віднести. Мови спілкування, стаж, освіту, soft skills не додавай.

Далі тексти для кроку 6, мовою оголошення (lang). Без довгих тире. Ні слова про рівень мови, про навчання, про
«дуже потрібна робота». Лише те, що є у фактах: не перебільшуй і не додумуй. Навички з basics кандидат знає на
рівні основ (робив з AI-агентом): у note і sentence не подавай їх як досвід («hands-on experience», «doświadczenie»)
і не бери їх у tech, спирайся на навички зі skill_lines.
note — нотатка до запиту на контакт у LinkedIn, ≤200 знаків: на яку роль подався і одна технологія з їхніх
вимог, яку кандидат справді робив.
tech — одна технологія з вимог вакансії, на якій кандидат має найсильніший факт.
sentence — одне речення від першої особи: що саме кандидат на ній зробив, з числом із факту.
fact — id цього факту.

Банк (YAML):
"""


def bank_for_model(b: dict) -> str:
    view = {
        "summaries": [{"id": s["id"], "when": s["when"]} for s in summaries(b)],
        "headline_names": [plain(it.get("short") or it["name"]) for cat, v in b["skills"].items() if cat != "basics"
                           for it in v["items"]],
        "skill_lines": {cat: [plain(it["name"]) for it in v["items"]] for cat, v in b["skills"].items() if cat != "basics"},
        "basics": [plain(it["name"]) for it in b["skills"]["basics"]["items"]],
        "facts": [{"id": f["id"], "role": f["role"], "text": plain(f["en"])} for f in b["facts"]],
        "learning": b["learning"], "never": b.get("never", []),
    }
    return yaml.safe_dump(view, allow_unicode=True, sort_keys=False)


def choose(client, b: dict, title: str, company: str, text: str) -> tuple[dict, dict]:
    r = client.messages.create(
        model=config.PACKAGE_MODEL, max_tokens=3000,  # with headroom: the thinking block also eats the output limit
        system=[{"type": "text", "text": RUBRIC + bank_for_model(b), "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"Вакансія: {title} · {company}\n\n{text}"}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
    if r.stop_reason != "end_turn":
        raise RuntimeError(f"stop_reason {r.stop_reason}")
    # A thinking block can come before the text (10.10 on the server) - take the first text block, like rank.score
    data = json.loads(next(x.text for x in r.content if x.type == "text"))
    u = r.usage
    return data, {"in": u.input_tokens, "out": u.output_tokens,  # keys as in rank.cost
                  "cache_read": u.cache_read_input_tokens or 0, "cache_write": u.cache_creation_input_tokens or 0}


def gaps(b: dict, raw: dict) -> list[dict]:
    """Gaps the bank knows nothing about yet. Category must be an existing one."""
    seen, out = known(b), []
    for g in raw.get("gaps", []):
        name = g["skill"].strip()
        if name and name.lower() not in seen:  # known ones do not take any of the three slots
            seen.add(name.lower())
            out.append({"skill": name, "category": g["category"] if g["category"] in b["skills"] else "automation"})
    return out[:3]


def clean(s: str) -> str:
    """Long dashes are banned by the owner's writing voice (letters and notes alike)."""
    return re.sub(r"\s*[—–]\s*", ", ", s).strip()


def letter(raw: dict, lang: str, title: str, site: str) -> tuple[str, str]:
    subject, body = LETTER[lang]
    sentence = clean(raw["sentence"])
    return subject.format(title=title), body.format(title=title, site=site, tech=clean(raw["tech"]),
                                                    sentence=sentence if sentence.endswith(".") else sentence + ".")




def pdf(page_html: str) -> tuple[bytes, int]:
    """(PDF, pages). WeasyPrint only inside the server image (no GTK on Windows)."""
    from weasyprint import HTML
    doc = HTML(string=page_html).render()
    return doc.write_pdf(), len(doc.pages)


def check_pdf(data: bytes, page_html: str) -> list[str]:
    """What is wrong with the PDF: we check the OUTPUT (extracted text), not the HTML. Empty = fine."""
    import io
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    got = " ".join(" ".join(p.extract_text() for p in r.pages).split())
    bad = [] if len(r.pages) == 1 else [f"сторінок {len(r.pages)}"]
    want = ["Jan Kowalski"] + (["RODO"] if 'lang="pl"' in page_html else [])
    return bad + [f"нема «{w}»" for w in want if w not in got]
