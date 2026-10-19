"""Step 3, 03.10: code sieve, model scoring (fake client), digest. Owner decisions 03.10."""
import json
import time
import types

import pytest

from jobbot import config, rank, store
from jobbot.job import Job

TEXT = "Wymagania: Python, n8n, integracje API, praca hybrydowa. " * 10


def job(title="Automation Specialist", url="https://x/1", seniority=(), cities=("Poznań",), remote=False, mode="",
        age_days=0):
    return Job("pracuj", title, "Acme", url, time.time() - age_days * 86400, "PL", cities=list(cities), remote=remote,
               mode=mode, seniority=list(seniority))


class FakeClient:
    """Returns the given score; counts calls."""
    def __init__(self, score=8, stop="end_turn"):
        self.calls, self.score, self.stop = [], score, stop
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        body = {"score": self.score, "why": "збіг задач", "matched": ["n8n"], "missing": ["Jira"]}
        return types.SimpleNamespace(
            stop_reason=self.stop, content=[types.SimpleNamespace(type="text", text=json.dumps(body))],
            usage=types.SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=3000,
                                        cache_creation_input_tokens=0))


@pytest.fixture
def facts(monkeypatch):
    monkeypatch.setattr(rank, "facts_text", lambda: "facts: []")


# --- sieve

def test_blacklisted_titles_dropped_languages_and_qa_kept():
    for t in ("Senior DevOps Engineer", "SAP Consultant", "Cyber Security Analyst", "Handlowiec", "Embedded C Engineer"):
        assert rank.route(job(t), TEXT, [])[0] == "drop", t
    # Owner decision 03.10: programming languages and QA are not rejected
    for t in ("Junior Java Developer", "Python or C++ Developer", "QA Automation Engineer", "Specjalista ds. wsparcia IT"):
        assert rank.route(job(t), TEXT, [])[0] == "model", t


def test_heavy_marks_go_to_low_list_without_model():
    assert rank.route(job(), TEXT, ["⚠️ стаж 3+ р."]) == ("low", "⚠️ стаж 3+ р.")
    assert rank.route(job(), TEXT, ["⚠️ senior, років не названо"])[0] == "low"
    assert rank.route(job(), TEXT, ["⚠️ мова: німецька"])[0] == "low"
    assert rank.route(job(), TEXT, ["⚠️ стаж 2+ р.", "⚠️ англ. від B2"])[0] == "model"


def test_pause_with_date_lifts_itself_and_backfills_group0_once(tmp_path, facts, monkeypatch):
    """11.10 (owner): 'switch the scan back on by itself on 14.10 at 22:00'; what accumulated during the pause - all of group 0 once."""
    from datetime import datetime
    monkeypatch.setattr(config, "SCORE_CAP", 1)
    flag, backlog = tmp_path / "paused", tmp_path / "backlog-once"
    monkeypatch.setattr(rank, "PAUSED", flag)
    monkeypatch.setattr(rank, "BACKLOG_ONCE", backlog)
    flag.write_text("2026-10-14 22:00\n", encoding="utf-8")
    db = store.connect(tmp_path / "t.db")
    poz = [job(url=f"https://x/p{i}") for i in range(3)]
    noon = datetime(2026, 10, 14, 12, 5, tzinfo=rank.WARSAW)
    out = step(db, poz, client=FakeClient(), now=noon)
    assert out["scored"] == 0 and "2026-10-14 22:00" in out["note"] and flag.exists() and not backlog.exists()
    out = step(db, poz, client=FakeClient(), now=noon.replace(hour=22, minute=7))
    assert not flag.exists() and not backlog.exists()  # the backfill ran and removed its flag
    assert out["scored"] == 3 and out["worthy"]  # all of group 0 over a cap of 1, there is a digest
    flag.write_text("", encoding="utf-8")  # empty file = pause without an end, as on 10.10
    assert step(db, poz, client=FakeClient(), now=noon)["note"].startswith("⏸ пауза (без строку)")


def test_no_text_is_not_scored():
    assert rank.route(job(), "", [])[0] == "notext"


def test_office_in_other_city_is_a_mark_not_a_drop():
    office = "Praca stacjonarna w biurze w Warszawie. " * 5
    assert rank.office_mark(job(cities=["Warszawa"]), office) == "⚠️ офіс: Warszawa"
    assert rank.office_mark(job(cities=["Poznań"]), office) is None
    assert rank.office_mark(job(cities=["Warszawa"]), office + " Praca hybrydowa.") is None
    assert rank.office_mark(job(cities=["Warszawa"], remote=True), office) is None


def test_office_mark_reads_site_mode_and_negated_remote():
    # a posting 06.10: 'zdalna' in a sentence with 'Nie' - not hybrid
    dtex = ("WAŻNE – PRACA STACJONARNA. Szukamy osoby do stałej pracy na miejscu, w siedzibie firmy w Wieluniu. "
            "Nie szukamy freelancerów, firm zewnętrznych ani osób zainteresowanych wyłącznie pracą zdalną.")
    assert rank.office_mark(job(cities=["Wieluń"]), dtex) == "⚠️ офіс: Wieluń"
    # a posting 06.10: not a word about the mode in the text, office only in the site field
    assert rank.office_mark(job(cities=["Gdańsk"], mode="office"), "Tworzenie automatyzacji n8n.") == "⚠️ офіс: Gdańsk"
    # the site field outweighs the text
    assert rank.office_mark(job(cities=["Gdańsk"], mode="hybrid"), dtex) is None
    assert rank.office_mark(job(cities=["Poznań"], mode="office"), dtex) is None


def test_queue_order_reachable_clean_first_office_elsewhere_last(tmp_path, facts, monkeypatch):
    """Owner decision 06.10: the cap is far below the daily inflow, so the reachable ones go first."""
    monkeypatch.setattr(config, "SCORE_CAP", 1)
    db = store.connect(tmp_path / "t.db")
    office = job(url="https://x/office", cities=["Wieluń"], mode="office")   # freshest
    hybrid = job(url="https://x/hybrid", cities=["Kraków"], mode="hybrid", age_days=1)
    b2 = job(url="https://x/b2", remote=True, age_days=2)
    poz = job(url="https://x/poz", cities=["Poznań"], mode="office", age_days=3)  # oldest
    marks = {office.url: ["⚠️ офіс: Wieluń"], hybrid.url: [], b2.url: ["⚠️ англ. від B2"], poz.url: []}
    assert [rank.group(j, marks[j.url]) for j in (office, hybrid, b2, poz)] == [2, 1, 1, 0]
    step(db, [office, hybrid, b2, poz], marks, client=FakeClient())
    assert store.score_row(db, poz.url) and store.score_row(db, office.url) is None


def test_older_than_20_days_is_not_scored(tmp_path, facts):
    db = store.connect(tmp_path / "t.db")
    c = FakeClient()
    out = step(db, [job(url="https://x/new", age_days=19), job(url="https://x/old", age_days=21)], client=c)
    assert out["scored"] == 1 and out["old"] == 1 and out["waiting"] == 0
    assert store.score_row(db, "https://x/old") is None


def test_no_credit_stops_after_first_call_and_gives_clean_fallback(tmp_path, facts):
    db = store.connect(tmp_path / "t.db")

    class Broke(FakeClient):
        def create(self, **kw):
            self.calls.append(kw)
            raise RuntimeError("Error code: 400 - Your credit balance is too low to access the Anthropic API.")
    c = Broke()
    # Fewer reachable than NO_CREDIT_TOP: a 'first 5 of the queue' cut would slip unreachable ones in
    jobs = [job(url=f"https://x/p{i}") for i in range(3)] \
        + [job(url=f"https://x/waw{i}", cities=["Kraków"], mode="hybrid") for i in range(4)]
    out = step(db, jobs, client=c)
    assert len(c.calls) == 1 and "🔴" in out["note"]  # do not hammer the remaining 39
    assert [j.url for j in out["no_credit"]] == ["https://x/p0", "https://x/p1", "https://x/p2"]


# --- model

def test_score_parses_clamps_and_caches_system(facts):
    c = FakeClient(score=14)
    data, usage = rank.score(c, "claude-sonnet-5-5", job(), TEXT, "facts: []")
    assert data["score"] == 10 and usage["cache_read"] == 3000
    sysblock = c.calls[0]["system"][0]
    assert sysblock["cache_control"] == {"type": "ephemeral"} and "facts" in sysblock["text"]
    assert c.calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_score_refuses_truncated_or_refused_answer():
    with pytest.raises(RuntimeError):
        rank.score(FakeClient(stop="max_tokens"), "claude-sonnet-5-5", job(), TEXT, "")


@pytest.mark.parametrize("title,dropped", [
    # cut (owner decision 07.10, titles from live scores of 1-2)
    ("IT Recruiter", True), ("Rekruter IT", True), ("Junior Accountant", True), ("Motion Designer (iGaming)", True),
    ("Junior Media Buyer", True), ("Senior SEO & GEO Specialist", True), ("Account Manager", True),
    ("Pracowniczka / Pracownik Magazynu", True), ("Technik Obiektu (K/M)", True), ("Business Development Specialist", True),
    # not cut: word boundary, a hiring process in the title, our field, UX/UI, programming languages
    # 'rekrutacja zdalna' - without rescue words, otherwise the test proves nothing (break check 08.10)
    ("Doradca klienta", False), ("Specjalista ds. wsparcia IT – rekrutacja zdalna", False),
    ("Specjalista ds. procesów magazynowych", False), ("Customer Care & Sales Support Specialist", False),
    ("UX Designer", False), ("Marketing Automation Specialist", False), ("Analityk / Analityczka HR", False),
    ("Specjalista ds. procesów HR", False), ("Junior PHP Developer", False), ("Junior Unreal Engine 5 Developer", False),
])
def test_other_profession_dropped_by_title(title, dropped):
    assert (rank.route(job(title=title), TEXT, [])[0] == "drop") is dropped


def evening():
    return rank.now_warsaw().replace(hour=22, minute=0)


def step(db, jobs, marks=None, client=None, now=None):
    """Evening scan by default: the full cap, the test does not depend on the hour it runs."""
    texts = {j.url: (TEXT, 0) for j in jobs}
    return rank.step(db, jobs, texts, marks or {j.url: [] for j in jobs}, client=client, now=now or evening())


def test_day_scan_takes_half_evening_tops_up_missed_day_gives_all(tmp_path, facts, monkeypatch):
    """Owner decision 07.10: the midday scan <= half of the cap, the evening one fills up to the full cap, the day in Warsaw time."""
    monkeypatch.setattr(config, "SCORE_CAP", 4)
    jobs = [job(url=f"https://x/{i}") for i in range(10)]
    db = store.connect(tmp_path / "t.db")
    noon = evening().replace(hour=12, minute=5)
    assert step(db, jobs, client=FakeClient(), now=noon)["scored"] == 2
    assert step(db, jobs, client=FakeClient(), now=evening())["scored"] == 2  # filled up to 4
    assert step(db, jobs, client=FakeClient(), now=evening())["scored"] == 0
    # no midday scan: the evening takes the whole cap
    db2 = store.connect(tmp_path / "t2.db")
    assert step(db2, jobs, client=FakeClient(), now=evening())["scored"] == 4


def test_budget_counts_from_warsaw_midnight_not_rolling_24h(tmp_path, monkeypatch):
    """07.10: a rolling 24 h window gave 0 at 12:11, because yesterday's scoring ran at 12:23. Yesterday does not count."""
    monkeypatch.setattr(config, "SCORE_CAP", 40)
    db = store.connect(tmp_path / "t.db")
    noon = evening().replace(hour=12, minute=11)
    yesterday = noon.timestamp() - 86400 + 12 * 60  # yesterday 12:23
    for i in range(40):
        db.execute("INSERT INTO scores VALUES (?, ?, 'm', 5, '{}', 0)", (f"https://y/{i}", yesterday))
    db.commit()
    assert rank.budget(db, noon) == 20


def test_daily_cap_scores_freshest_first_and_counts_waiting(tmp_path, facts, monkeypatch):
    monkeypatch.setattr(config, "SCORE_CAP", 2)
    db = store.connect(tmp_path / "t.db")
    jobs = [job(url=f"https://x/{i}") for i in range(5)]  # already sorted: the first ones are the freshest
    c = FakeClient()
    out = step(db, jobs, client=c)
    assert out["scored"] == 2 and out["waiting"] == 3
    assert [kw["messages"][0]["content"] for kw in c.calls] and store.score_row(db, "https://x/0")
    assert store.score_row(db, "https://x/4") is None
    out = step(db, jobs, client=c)  # same day: the cap is used up
    assert out["scored"] == 0 and len(c.calls) == 2


def test_backlog_once_scores_all_group0_over_cap_then_flag_is_gone(tmp_path, facts, monkeypatch):
    """Owner decision 08-09.10: a Poznan posting (8.5/10) waited in the tail from 01.10. Once, all of group 0 up to 30 days, over the cap."""
    monkeypatch.setattr(config, "SCORE_CAP", 1)
    flag = tmp_path / "backlog-once"
    flag.touch()
    monkeypatch.setattr(rank, "BACKLOG_ONCE", flag)
    db = store.connect(tmp_path / "t.db")
    poz = [job(url=f"https://x/poz{a}", age_days=a) for a in (0, 9, 25)]
    waw = [job(url=f"https://x/waw{i}", cities=["Kraków"], mode="hybrid") for i in range(3)]
    out = step(db, poz + waw, client=FakeClient())
    assert out["scored"] == 4 and all(store.score_row(db, j.url) for j in poz)  # all of group 0 + a cap of 1
    assert not flag.exists()
    assert step(db, waw, client=FakeClient())["scored"] == 0  # next scan: the normal cap again


def test_group0_left_over_the_cap_is_counted_for_the_header(tmp_path, facts, monkeypatch):
    """Sensor 11.10 instead of a rule: group 0 comes first; if it does not fit into the cap - waiting0 > 0, other groups are not counted."""
    monkeypatch.setattr(config, "SCORE_CAP", 2)
    db = store.connect(tmp_path / "a.db")
    waw = [job(url=f"https://x/waw{i}", cities=["Kraków"], mode="hybrid") for i in range(3)]
    out = step(db, waw + [job(url="https://x/poz")], client=FakeClient())
    assert store.score_row(db, "https://x/poz") and out["waiting"] == 2 and out["waiting0"] == 0
    out = step(store.connect(tmp_path / "b.db"), [job(url=f"https://x/p{i}") for i in range(3)], client=FakeClient())
    assert out["scored"] == 2 and out["waiting0"] == 1


def test_paused_collects_without_model_and_digest(tmp_path, facts, monkeypatch):
    """Owner decision 10.10: while per-posting CVs are being built, the scan only collects. Even an already scored 8+ does not go to the digest."""
    flag = tmp_path / "paused"
    monkeypatch.setattr(rank, "PAUSED", flag)
    db = store.connect(tmp_path / "t.db")
    old = job(url="https://x/old")
    step(db, [old], client=FakeClient())
    flag.touch()
    c = FakeClient()
    out = step(db, [old, job(url="https://x/new")], client=c)
    assert c.calls == [] and out["scored"] == 0 and out["waiting"] == 1
    assert out["worthy"] == out["digest"] == [] and out["note"].startswith("⏸")


def test_already_scored_is_not_scored_again(tmp_path, facts):
    db = store.connect(tmp_path / "t.db")
    c = FakeClient()
    step(db, [job()], client=c)
    step(db, [job()], client=c)
    assert len(c.calls) == 1


def test_digest_applies_penalty_threshold_and_top(tmp_path, facts, monkeypatch):
    monkeypatch.setattr(config, "DIGEST_TOP", 2)
    db = store.connect(tmp_path / "t.db")
    a, b, c_, d = (job(url=f"https://x/{k}") for k in "abcd")
    for j, s in ((a, 9), (b, 7), (c_, 6), (d, 8)):
        store.save_score(db, j.url, "m", {"score": s, "why": "", "matched": [], "missing": []}, 0)
    marks = {a.url: [], b.url: [], c_.url: ["⚠️ англ. від B2"], d.url: ["⚠️ стаж 2+ р.", "⚠️ офіс: Kraków"]}
    out = step(db, [a, b, c_, d], marks)
    # d: 8-2=6, c: 6-1=5 - below the threshold; top-2 = a(9), b(7)
    assert [(f, j.url) for f, j, _ in out["digest"]] == [(9, a.url), (7, b.url)]


def test_no_key_no_scoring_but_report_works(tmp_path, facts):
    db = store.connect(tmp_path / "t.db")
    out = step(db, [job()])
    assert out["scored"] == 0 and "ключа" in out["note"] and out["digest"] == []


def test_one_failed_call_does_not_stop_the_rest(tmp_path, facts):
    db = store.connect(tmp_path / "t.db")

    class Flaky(FakeClient):
        def create(self, **kw):
            if not self.calls:
                self.calls.append(kw)
                raise RuntimeError("503")
            return super().create(**kw)
    out = step(db, [job(url="https://x/1"), job(url="https://x/2")], client=Flaky())
    assert out["scored"] == 1 and out["errors"] == 1 and "503" in out["note"]


def test_quiet_day_digest_does_not_pad_with_weak_ones(tmp_path, facts):
    # Owner decision 03.10: top 10, but not below the threshold - on a quiet day we do not pad with junk (threshold 5 since 19.10, Haiku)
    db = store.connect(tmp_path / "t.db")
    a, b = job(url="https://x/a"), job(url="https://x/b")
    store.save_score(db, a.url, "m", {"score": 9, "why": "", "matched": [], "missing": []}, 0)
    store.save_score(db, b.url, "m", {"score": 4, "why": "", "matched": [], "missing": []}, 0)
    assert [j.url for _, j, _ in step(db, [a, b])["digest"]] == [a.url]


def test_old_sonnet_five_stays_out_haiku_five_comes_in(tmp_path, facts):
    """19.10 switch to Haiku 5.5 with threshold 5 (bake-off: Haiku 5 ~ Sonnet 6). Old Sonnet-5 scores from the database must not
    flood the digest 10 per scan."""
    db = store.connect(tmp_path / "t.db")
    s, h = job(url="https://x/s"), job(url="https://x/h")
    store.save_score(db, s.url, "claude-sonnet-5-5", {"score": 5, "why": "", "matched": [], "missing": []}, 0)
    store.save_score(db, h.url, "claude-haiku-5-5", {"score": 5, "why": "", "matched": [], "missing": []}, 0)
    assert [j.url for _, j, _ in step(db, [s, h])["digest"]] == [h.url]


def test_scoring_leaves_room_for_haiku_thinking():
    """Bake-off 19.10: Haiku 5.5 thinks adaptively, with max_tokens 1024 30 of 85 failed (stop_reason max_tokens)."""
    c = FakeClient()
    rank.score(c, config.SCORE_MODEL, job(), TEXT, "facts")
    assert c.calls[0]["max_tokens"] >= 4096 and c.calls[0]["model"] == "claude-haiku-5-5"


def test_package_stays_on_sonnet_when_scoring_is_haiku(monkeypatch):
    """cv.choose used SCORE_MODEL: switching scoring to Haiku would silently switch the CV and letter too."""
    from pathlib import Path
    from jobbot import cv
    monkeypatch.setattr(cv, "BANK", Path(__file__).with_name("bank_fixture.yaml"))
    c = FakeClient()
    try:
        cv.choose(c, cv.load(), "t", "c", "text")
    except Exception:  # the fake's answer does not match the package schema - we only need the request's model
        pass
    assert c.calls and c.calls[0]["model"] == config.PACKAGE_MODEL == "claude-sonnet-5-5"


def test_warsaw_hybrid_is_group0_warsaw_office_is_not():
    """19.10: two Warsaw-hybrid postings (later scored 9 and 8) waited in group 1 from 09-12.10 and never got past the cap.
    Owner priorities: remote / Poznan / Warsaw hybrid."""
    assert rank.group(job(cities=("Warszawa",), mode="hybrid"), []) == 0
    assert rank.group(job(cities=("Warszawa",), mode="office"), []) == 1
    assert rank.group(job(cities=("Warszawa",), mode="hybrid"), ["⚠️ англ. від B2"]) == 1
    assert rank.group(job(cities=("Wrocław",), mode="hybrid"), []) == 1
