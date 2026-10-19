"""Step 4, 10.10: CV from the bank (owner decision: the model only chooses, code lets only the bank through; gaps become questions).
Word-for-word match with CV v4 was checked separately on the real bank (the bank is not in git)."""
import re
from pathlib import Path

import pytest

from jobbot import cv


@pytest.fixture(autouse=True)
def bank(monkeypatch):
    monkeypatch.setattr(cv, "BANK", Path(__file__).with_name("bank_fixture.yaml"))


def test_default_render_keeps_bank_order_and_all_basics():
    b = cv.load()
    t = cv.text_of(cv.render(b, cv.default_choice(b, "en")))
    assert "Automation developer: Python, n8n, Docker, REST APIs, Google Sheets. Body EN. Tail EN." in t
    assert t.index("F1 en") < t.index("F2 en") < t.index("F3 en 0 of 12") < t.index("M1 en")
    assert "Basics: SQL, Power BI" in t and "NumPy" not in t and "RODO" not in t


def test_polish_uses_polish_names_and_rodo():
    b = cv.load()
    t = cv.text_of(cv.render(b, cv.default_choice(b, "pl")))
    assert "Python, n8n, Docker, REST API, Google Sheets. Body PL." in t
    assert "Integracje: REST API, Google Sheets i Drive API" in t and "Docker i Docker Compose" in t
    assert t.endswith("angielski Zgoda RODO.")


def test_model_choice_only_passes_what_bank_has():
    """Red line 19.09: an invented skill, an unapproved summary, a foreign id, Excel from learning - none get through."""
    b = cv.load()
    c = cv.validate(b, {"lang": "en", "summary": "data", "headline": ["Kubernetes", "Docker", "Docker"],
                        "priority": ["m3", "zzz", "f3"], "skill_lines": ["infrastructure", "zzz"],
                        "basics": ["Excel", "Power BI"]})
    assert c["summary"] == "automation" and c["headline"] == ["Docker", "Python", "n8n", "REST APIs", "Google Sheets"]
    assert c["priority"] == ["m3", "f3"] and c["skill_lines"][0] == "infrastructure" and c["basics"] == ["Power BI", "SQL"]
    t = cv.text_of(cv.render(b, c))
    assert t.index("F3 en") < t.index("F1 en") and t.index("M3 en") < t.index("M1 en")
    assert t.index("Infrastructure:") < t.index("Automation:") and "Basics: Power BI, SQL" in t


def test_basics_always_all_asked_first_hidden_never():
    """Owner decision 10.10: 'Basics' are never removed from the CV; hidden ones (SciPy) are never rendered."""
    b = cv.load()
    for asked, line in (([], "Basics: SQL, Power BI"), (["Power BI", "SciPy"], "Basics: Power BI, SQL")):
        t = cv.text_of(cv.render(b, cv.validate(b, {"lang": "en", "basics": asked})))
        assert line in t and "SciPy" not in t, asked
    raw = {**cv.default_choice(b, "en"), "basics": ["SciPy", "SQL"]}  # bypassing validate: the second layer is render itself
    assert "SciPy" not in cv.text_of(cv.render(b, raw))


def test_gap_answers_go_to_right_place_and_are_not_asked_again():
    """4 levels (owner decision 10.10): 🔧 -> category line, 👌 -> 'Basics', 📚 -> learning, ❌ -> never ask again."""
    raw = {"gaps": [{"skill": "Jira", "category": "integrations"}, {"skill": "Excel", "category": "automation"},
                    {"skill": "n8n", "category": "automation"}, {"skill": "Tableau", "category": "zzz"}]}
    assert [g["skill"] for g in cv.gaps(cv.load(), raw)] == ["Jira", "Tableau"]  # Excel in learning, n8n already present
    b = cv.load([("Jira", "regular", "integrations"), ("Tableau", "basics", "zzz"), ("Go", "never", "x")])
    assert cv.gaps(b, raw | {"gaps": raw["gaps"] + [{"skill": "go", "category": "x"}]}) == []
    c = cv.validate(b, {"lang": "en", "basics": ["Tableau"]})
    t = cv.text_of(cv.render(b, c))
    assert "Integrations: REST APIs, Google Sheets & Drive API, Jira" in t and "Basics: Tableau, SQL, Power BI" in t
    assert not re.search(r"\bGo\b", t)


def test_letter_follows_template_and_drops_long_dashes():
    subject, body = cv.letter({"tech": "n8n", "sentence": "built a pipeline — 200+ posts a day"}, "pl",
                              "Junior AI", "pracuj.pl")
    assert subject == "Aplikacja: Junior AI, Jan Kowalski"
    assert "Najbliżej Waszych wymagań: n8n: built a pipeline, 200+ posts a day." in body and "—" not in body
    assert body.startswith("Dzień dobry,") and "Z poważaniem,\nJan Kowalski" in body
