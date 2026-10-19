import time

from jobbot.filters import drop_reason
from jobbot.job import Job
from jobbot.scan import merge

NOW = time.time()


def job(**kw):
    base = dict(source="t", title="Python Developer", company="Acme", url="u", posted_at=NOW - 3600, country="PL")
    return Job(**{**base, **kw})


def test_poland_any_city_passes():
    assert drop_reason(job(cities=["Gdańsk"]), 1, NOW) is None


def test_abroad_office_dropped_abroad_remote_kept():
    assert drop_reason(job(country="UA", cities=["Київ"]), 1, NOW) == "локація"
    assert drop_reason(job(country="UA", remote=True), 1, NOW) is None


def test_industrial_automation_dropped_by_title_and_category():
    assert drop_reason(job(title="Programista PLC"), 1, NOW) == "промислова автоматика"
    assert drop_reason(job(title="Automatyk/Automatyczka"), 1, NOW) == "промислова автоматика"
    assert drop_reason(job(category="automation"), 1, NOW) == "промислова автоматика"


def test_ai_automation_is_not_industrial():
    # The word 'automation' in a title is not industrial by itself: it is our main segment
    assert drop_reason(job(title="AI Automation Engineer"), 1, NOW) is None


def test_window():
    assert drop_reason(job(posted_at=NOW - 2 * 86400), 1, NOW) == "старше вікна"
    assert drop_reason(job(posted_at=NOW - 2 * 86400), 7, NOW) is None


def test_old_but_confirmed_open_is_kept_with_age():
    # one board on 29.09: 1 240 of 1 678 older than 30 days, and all still open by validTo
    assert drop_reason(job(posted_at=NOW - 90 * 86400, open_until=NOW + 86400), 30, NOW) is None
    assert drop_reason(job(posted_at=NOW - 90 * 86400, open_until=NOW - 86400), 30, NOW) == "старше вікна"


def test_merge_keeps_latest_open_until():
    m = merge([job(open_until=0.0), job(open_until=NOW + 86400)])
    assert list(m.values())[0].open_until == NOW + 86400


def test_merge_same_job_from_several_cities():
    m = merge([job(cities=["Kraków"]), job(cities=["Wrocław"], title="python  developer ")])
    assert len(m) == 1
    assert list(m.values())[0].cities == ["Kraków", "Wrocław"]
