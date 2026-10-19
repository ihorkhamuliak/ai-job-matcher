"""Money floor, 06.10. The strings are live shapes from the 06.10 scan (numbers are our own)."""
from jobbot import money, rank


def test_board_shapes_month_hour_day_year():
    assert money.ceiling("5 000–5 500 zł brutto / mies.") == 5500          # narrow no-break space
    assert money.ceiling("80–95 zł netto (+ VAT) / godz.") == 95 * 168     # hourly
    assert money.ceiling("120-140 zł/hr. net (+ VAT)") == 140 * 168        # theprotocol
    assert money.ceiling("800-1000 PLN/day b2b") == 1000 * 21              # daily
    assert money.ceiling("60000-90000 PLN/year any") == 7500               # yearly
    assert money.ceiling("5500-5800 PLN/monthly brutto") == 5800           # olx
    assert money.ceiling("35.5-40 PLN/hourly brutto") == 40 * 168          # fraction
    assert money.ceiling("$1000–1700") == 1700 * 4.0                       # no unit = month


def test_several_contracts_take_the_best_ceiling():
    assert money.ceiling("4000-5000 PLN/month permanent; 7000-9000 PLN/month b2b") == 9000


def test_no_judgement_when_unsure():
    # Trap 1: an hourly rate with a wrong unit
    assert money.ceiling("100-100 PLN/Month B2B") is None
    # Trap 2: a lower bound without a ceiling
    assert money.ceiling("From 5000 PLN") is None
    assert money.ceiling("від $1000") is None
    assert money.ceiling("4000-5000 PLN/month permanent; From 8000 PLN/month b2b") is None
    # Trap 3: no unit and not dollars - a daily rate would read as monthly
    assert money.ceiling("1200 - 1500 PLN") is None
    assert money.ceiling("3000 - 4000 GBP") is None   # unknown currency
    assert money.mark("") is None


def test_generous_rate_keeps_borderline():
    assert money.mark("1500 USD/month") is None             # 6 000 is on the edge, stays
    assert money.mark("40 zł brutto / godz.") is None       # 6 720
    assert money.mark("35 zł brutto / godz.") is not None   # 5 880
    assert money.mark("5 999 zł brutto / mies.") is not None


