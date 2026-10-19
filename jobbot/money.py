"""Money floor (owner decision 06.10): salary ceiling below MONEY_FLOOR PLN/month -> warning, 'lower priority', no model.
A posting at $550-700 got 6/10 on 06.10 and took an application slot, because salary played no part in selection at all.

We judge only what we read unambiguously; the rest = None (not filtered). The exchange rate is generous: a borderline posting survives.
String shapes were taken from a live scan of all 10 boards on 06.10."""
import re

from . import config

# Above the market rate: $1 500 -> 6 000 and stays
RATE = {"zł": 1.0, "pln": 1.0, "usd": 4.0, "$": 4.0, "eur": 4.3, "€": 4.3}
PER_MONTH = {"hour": 168, "day": 21, "month": 1, "year": 1 / 12}
_UNIT = [("hour", r"/\s*(?:godz|hr|hour)"), ("day", r"/\s*(?:day|dzie)"), ("year", r"/\s*year"),
         ("month", r"/\s*(?:mies|mth|month)")]
_CUR = re.compile(r"zł|pln|usd|eur|\$|€", re.I)
# 'From 5 000 PLN', 'from $1000', 'od 40 zl': this is a lower bound, there is no ceiling
_FROM = re.compile(r"^\s*(?:from|від|od)\b", re.I)
# A monthly range below this is really an hourly one with a wrong unit ('100-100 PLN/Month B2B' on one board)
MONTH_SANITY = 1000


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def ceiling(salary: str) -> float | None:
    """The highest ceiling among the contracts in the string, PLN per month. None - we do not judge."""
    best = None
    for part in salary.split(";"):
        part = re.sub(r"(?<=\d)[\s   ](?=\d)", "", part)
        if not part.strip():
            continue
        if _FROM.search(part):
            return None  # at least one contract without a ceiling - we cannot say it is too little
        cur = _CUR.search(part)
        nums = [_num(x) for x in re.findall(r"\d+(?:[.,]\d+)?", part)]
        if not cur or not nums:
            return None
        unit = next((u for u, rx in _UNIT if re.search(rx, part, re.I)), None)
        if unit is None:
            if cur.group(0) != "$":  # some boards count monthly; '5000 - 8000 PLN' without a unit is unknown
                return None
            unit = "month"
        top = max(nums) * RATE[cur.group(0).lower()]
        if unit == "month" and top < MONTH_SANITY:  # in PLN: $700 is a real monthly figure, 100 PLN is not
            return None
        value = top * PER_MONTH[unit]
        best = value if best is None else max(best, value)
    return best


def mark(salary: str) -> str | None:
    c = ceiling(salary) if salary else None
    if c is not None and c < config.MONEY_FLOOR:
        return f"⚠️ гроші: до {c:,.0f} zł/міс".replace(",", " ")
    return None
