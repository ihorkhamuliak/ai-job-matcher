"""Step 2b: experience and languages in code (03.10). We mark, we do not hide (owner decision 28.09).

Owner decision 03.10:
- experience: warning from 2 years (1 year is clean). A number in the text outweighs the site field. Without a number: senior / lead /
  expert is a warning, mid is a soft mark, junior is clean. 'Wymagane doswiadczenie' without a number = soft
- languages (levels come from the facts bank): English from B2 is a warning, a required third language is a warning,
  Polish 'biegla / C1' is soft; 'mile widziane / nice to have' is not counted"""
import re

from .job import Job

MIN_YEARS = 2

# A 'preferred, not required' sentence: its requirements are not counted. 'Ideally / preferably' only at the start of a sentence:
# '4+ years in operations, preferably in marketing' narrows the field, the experience stays a requirement (03.10)
_NICE = re.compile(r"nice[ -]to[ -]have|\bis a plus|would be a plus|big plus|advantage|mile widzian|\batut|plusem"
                   r"|dodatkowym atutem|бажано|буде перевагою|буде плюсом|optional|is preferred"
                   r"|^(ideally|preferab\w*|preferowan\w*)",
                   re.I)
_EXP_WORD = re.compile(r"experience|doświadcz|praktyk|podobnym stanowisku|similar (role|position)|досвід|опыт", re.I)
_YEAR = r"(?:years?|yrs?|lat[a]?|rok(?:u)?|років|роки|рік)"
_NUM_YEARS = re.compile(rf"(\d{{1,2}})(?:[.,]5)?\s*(?:\+|-|–|to|do|або)?\s*(?:\d{{1,2}}\s*)?\+?\s*{_YEAR}\b", re.I)
_WORD_YEARS = {r"\broczn|\bjednoroczn|\bone year|\bрічн": 1, r"dwulet|dwa lata|\btwo years|дворічн|два роки": 2,
               r"trzylet|trzy lata|\bthree years|трирічн|три роки": 3, r"kilkulet|several years|kilka lat|кілька років": 3,
               r"czteroletn|cztery lata|four years": 4, r"pięcioletn|pięć lat|five years|п'ять років": 5}

_HIGH = re.compile(r"senior|expert|ekspert|lead|manager|menedżer|kierownik|c_level|head|starszy|principal|staff"
                   r"|dyrektor|director", re.I)
_MID = re.compile(r"\bmid|regular|medium|specjalista", re.I)
_LOW = re.compile(r"junior|trainee|intern|praktykant|stażyst|\bstaż\b|asystent|bez doświadczenia|młodszy", re.I)
_TITLE_HIGH = re.compile(r"\b(senior|sr\.?|lead|principal|staff|head of|starszy|starsza|ekspert\w*|expert)\b", re.I)

_EN = r"(?:english|angielsk\w*|англійськ\w*)"
_EN_HIGH = re.compile(
    rf"{_EN}[^.\n]{{0,40}}\b(B2|C1|C2|upper[- ]intermediate|advanced|fluent\w*|proficien\w*|biegł\w*|zaawansowan\w*"
    rf"|komunikatywn\w*|bardzo dobr\w*|very good|excellent)\b"
    rf"|\b(B2|C1|C2|upper[- ]intermediate|advanced|fluent|fluency|proficien\w*|biegł\w*|zaawansowan\w*|komunikatywn\w*"
    rf"|bardzo dobr\w*|very good|excellent)\b[^.\n]{{0,40}}{_EN}", re.I)
# 19.10: 'Strong written and spoken English' without a level. 'strong' only next to the language: 'strong technical
# curiosity, good English' is not a requirement (measured 19.10: 9 new, 4 among 6+, all genuine)
_EN_STRONG = re.compile(rf"\bstrong\b(?:\s+(?:written|spoken|verbal|and|or|&))*\s+{_EN}"
                        rf"|\bstrong\b[^.\n]{{0,40}}\bin {_EN}|{_EN}\W{{1,3}}strong\b", re.I)
_PL = r"(?:polish|polsk\w*)"
_PL_HIGH = re.compile(rf"{_PL}[^.\n]{{0,30}}\b(C1|C2|native|ojczyst\w*|biegł\w*)\b"
                      rf"|\b(C1|C2|native|ojczyst\w*|biegł\w*|fluen\w*)\b[^.\n]{{0,30}}{_PL}", re.I)
_THIRD = {"німецька": r"german|niemieck\w*|deutsch|німецьк\w*", "французька": r"french|francusk\w*|французьк\w*",
          "нідерландська": r"dutch|niderlandzk\w*|holendersk\w*", "італійська": r"italian|włosk\w*",
          "іспанська": r"spanish|hiszpańsk\w*", "чеська": r"czech|czesk\w*", "шведська": r"swedish|szwedzk\w*",
          "норвезька": r"norwegian|norwesk\w*", "данська": r"danish|duńsk\w*", "фінська": r"finnish|fińsk\w*",
          "португальська": r"portuguese|portugalsk\w*", "угорська": r"hungarian|węgiersk\w*",
          "словацька": r"slovak|słowack\w*", "румунська": r"romanian|rumuńsk\w*"}
# A language as a candidate requirement: a level or a proficiency word. 'speak', 'communication' removed 03.10:
# 'consultants who speak French' describes the company, not a requirement
# 'level' and 'skills' removed 03.10: 'rynku niemieckim ... senior-level' is a market, not a language
_LANG_REQ = re.compile(r"\b(A2|B1|B2|C1|C2)\b|fluen\w*|biegł\w*|komunikatywn\w*|znajomoś\w*|knowledge|proficien\w*"
                       r"|native|required|wymagan\w*|must|command of|poziom\w*|володі\w*|знання", re.I)
# A third language is not required when it is an alternative to a language the owner knows ('rosyjskiego lub niemieckiego', 'English or German'),
# or when it is a benefit ('English/German language lessons')
_LANG_ALT = re.compile(r"\b(or|lub|або|albo)\b[^.]{0,30}\b(english|angielsk\w*|polish|polsk\w*|russian|rosyjsk\w*"
                       r"|ukrainian|ukraińsk\w*)|\b(english|angielsk\w*|polish|polsk\w*|russian|rosyjsk\w*|ukrainian"
                       r"|ukraińsk\w*)\b[^.]{0,30}\b(or|lub|або|albo)\b", re.I)
_LANG_PERK = re.compile(r"lesson|lekcj\w*|\bkurs\w*|course|classes|nauk\w*", re.I)
# English where a lower level is explicitly accepted ('B1/B2', 03.10): no warning
_EN_LOW = re.compile(r"\b(A1|A2|B1)\b|pre[- ]intermediate|\bintermediate\b(?<!upper.intermediate)|podstawow\w*|basic", re.I)
# 11.10 (a posting the owner skipped): 'Polish and English for daily team communication' without a level = spoken English every day
_EN_DAILY = re.compile(rf"{_EN}[^.\n]{{0,50}}\b(daily|codzienn\w*|team communication|communicat\w*|komunikacj\w*|spoken|"
                       rf"speak\w*|meetings?|spotkani\w*|calls?|rozmow\w*)\b|\b(daily|codzienn\w*)\b[^.\n]{{0,40}}{_EN}", re.I)
# 11.10 ('Solid Python basics: data structures, functions, classes, exceptions'): a requirement to write Python unassisted.
# The facts bank lists Python as AI-assisted work, and a screening would test it. 'basic / podstawy Pythona' without
# 'solid' is not marked. Removed once the learning plan closes the hands-on Python stage
_PY_WORD = r"(?:python\w*|pythona)"
_PY_STRONG = r"(?:solid|strong|very good|good|dobr\w*|bardzo dobr\w*|zaawansowan\w*|proficien\w*|commercial|komercyjn\w*|confident|впевнен\w*|excellent|hands-on)"
_PY_HANDS = re.compile(rf"{_PY_WORD}[^.\n]{{0,40}}\b{_PY_STRONG}\b|\b{_PY_STRONG}\b[^.\n]{{0,40}}{_PY_WORD}"
                       r"|\boop\b|object[- ]oriented|obiektow\w*|data structures|struktur\w* danych|live[- ]coding"
                       r"|coding (task|interview)|zadani\w* (programistyczn|rekrutacyjn)\w*", re.I)
# 'coding challenges' removed after the 11.10 measurement: they are company events next to 'company parties', not a requirement (2 of 9)
# A benefit, not a requirement: 'Lekcje angielskiego z native speakerem', 'English Speaking Club' (measured 11.10)
_EN_PERK = re.compile(r"lekcj\w*|lesson\w*|club|klub\w*|kurs\w*|course\w*|zaję\w*", re.I)
# 'N+ years' with a plus is a requirement even without the word 'experience' ('6+ years hands-on ML', 03.10); company age is not written this way
_PLUS_YEARS = re.compile(rf"(\d{{1,2}})\s*\+\s*{_YEAR}\b", re.I)


# Section headers after which 'preferred' ends
_HEADER = re.compile(r"^(requirements?|wymagania|nasze wymagania|czego oczekujemy|must[ -]have|your profile|twój profil"
                     r"|qualifications|responsibilities|obowiązki|zakres obowiązków|we offer|what we offer|oferujemy"
                     r"|benefits?|about|o nas|вимоги|обов'язки|ми пропонуємо)\b", re.I)
# End of a sentence, but not an abbreviation: 'Min. 2 lata' was split into 'Min.' and '2 lata' without the word 'experience' (03.10)
_SENTENCE = re.compile(r"(?<!\bmin\.)(?<!\bnp\.)(?<!\bok\.)(?<!\btj\.)(?<!e\.g\.)(?<!i\.e\.)(?<!m\.in\.)(?<=[.;!?])\s+", re.I)
_NICE_START = re.compile(r"(nice[ -]to[ -]have|mile widzian\w*|будe перевагою|бажано|optional)", re.I)


def _segments(line: str, commas: bool) -> list[str]:
    """Line -> sentences. Two boards return everything as one line with headers glued to words
    ('outcomesRequirements10+ years', 03.10): without splitting, a single 'advantage' dropped the whole text.
    commas: one board joins section items with commas, and 'atutem bedzie Jira' dropped 'minimum 4 lata' next to it."""
    line = re.sub(r"(?<=[a-ząćęłńóśźż.:)’])(?=[A-ZĄĆĘŁŃÓŚŹŻ])", "\n", line)
    parts = [s for part in line.split("\n") for s in _SENTENCE.split(part)]
    if commas:
        parts = [c for s in parts for c in re.split(r",\s*", s)]
    return [s.strip() for s in parts if s.strip()]


def _lines(text: str, source: str = "") -> list[str]:
    """Sentences with required items. 'Nice to have' switches off the sentences below it until the next header.
    One board: a section = a line, so 'preferred' ends with the line."""
    out, nice = [], False
    for line in text.splitlines():
        if source == "pracuj":
            nice = False
        for s in _segments(line, source == "pracuj"):
            if _HEADER.match(s) and not _NICE.search(s):
                nice = False
            if _NICE_START.match(s):
                nice = True
            # 'preferred' in brackets applies to the brackets, not to the requirement next to it ('2 lata w branzy (mile widziane TETRA)')
            if not nice and not _NICE.search(re.sub(r"\([^)]*\)", "", s)):
                out.append(s)
    return out


def years(text: str, source: str = "") -> int | None:
    """The largest number of years of experience among required items; None = no number."""
    found = []
    for line in _lines(text, source):
        found += [int(m.group(1)) for m in _PLUS_YEARS.finditer(line)]
        if not _EXP_WORD.search(line):
            continue
        found += [int(m.group(1)) for m in _NUM_YEARS.finditer(line)]
        found += [n for rx, n in _WORD_YEARS.items() if re.search(rx, line, re.I)]
    return max(found) if found else None


def level(job: Job) -> str:
    """Level class from the site field and the title: high / mid / low / '' (the site does not say). Several levels = the lowest."""
    if m := re.match(r"([\d.]+)\+ р\.", " ".join(job.seniority)):  # one board gives experience in months
        return "high" if float(m.group(1)) >= MIN_YEARS else "low"
    levels = re.split(r"\s*/\s*(?=[a-zA-Z])", "/".join(job.seniority)) if job.seniority else []
    # Within a single level 'Starszy specjalista' = high, even though 'specjalista' is mid (03.10)
    found = {("low" if _LOW.search(lv) else "high" if _HIGH.search(lv) else "mid" if _MID.search(lv) else "")
             for lv in levels}
    for cls in ("low", "mid", "high"):
        if cls in found:
            return cls
    return "high" if _TITLE_HIGH.search(job.title) else ""


def marks(job: Job, text: str) -> list[str]:
    out = []
    y = years(text, job.source)
    if y is not None:
        if y >= MIN_YEARS:
            out.append(f"⚠️ стаж {y}+ р.")
    elif (lv := level(job)) == "high" or _TITLE_HIGH.search(job.title):
        out.append("⚠️ senior, років не названо")
    elif lv == "mid":
        out.append("mid, років не названо")
    elif any("wymagane doświadczenie" in s.lower() for s in job.seniority):
        out.append("стаж просять, без цифри")
    lines = _lines(text, job.source)
    if any((_EN_HIGH.search(line) or _EN_STRONG.search(line)) and not _EN_LOW.search(line) for line in lines):
        out.append("⚠️ англ. від B2")
    elif any(_EN_DAILY.search(line) and not _EN_LOW.search(line) and not _EN_PERK.search(line) for line in lines):
        out.append("⚠️ англ. щодня в команді")
    if any(_PY_HANDS.search(line) for line in lines):
        out.append("⚠️ Python руками")
    # 'preferred' in brackets applies to the language in brackets: 'good English (German language skills are an advantage)'
    lang_lines = [re.sub(r"\([^)]*\)", lambda m: "" if _NICE.search(m.group(0)) else m.group(0), line) for line in lines]
    third = [name for name, rx in _THIRD.items()
             if re.search(rf"\b({rx})\b", job.title, re.I)
             or any(re.search(rf"\b({rx})\b", line, re.I) and _LANG_REQ.search(line)
                    and not _LANG_ALT.search(line) and not _LANG_PERK.search(line) for line in lang_lines)]
    if third:  # one mark: 'German, French, Spanish or another European language' is a single requirement (03.10)
        out.append("⚠️ мова: " + "/".join(third))
    if any(_PL_HIGH.search(line) for line in lines):
        out.append("⚠️ польська C1")  # 19.10: the facts bank has Polish below C1 -> soft, minus 1 (measured: 1 of 15 among 6+)
    return out
