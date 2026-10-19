"""Public scan on synthetic postings: every step after the source is the production code."""
import time

from jobbot import scan, store
from jobbot.job import Job


def test_merge_keeps_one_posting_with_all_cities():
    a = Job("demo", "Python Developer", "Acme", "https://example.com/a", time.time(), "PL", cities=["Poznań"])
    b = Job("demo", "Python Developer", "Acme", "https://example.com/a", time.time(), "PL", cities=["Warszawa"])
    merged = scan.merge([a, b])
    assert len(merged) == 1 and next(iter(merged.values())).cities == ["Poznań", "Warszawa"]


def test_demo_scan_marks_drops_and_reports_without_api_key(tmp_path, monkeypatch, capsys):
    db = store.connect(tmp_path / "t.db")
    monkeypatch.setattr(scan.store, "connect", lambda: db)
    scan.main(["--no-mark"])
    out = capsys.readouterr().out
    assert "Raw 5 -> unique 5" in out
    assert "промислова автоматика 1" in out  # PLC programmer: industrial automation, cut before the queue
    # Acme and Contoso go to the model; Fabrikam asks 6+ years (heavy warning); the phone helpdesk is dropped by title
    assert "to model 2 · heavy warnings 1 · dropped by title 1" in out
    assert "scored now 0" in out  # no key in tests (conftest): the report still works
    contoso = store.text_row(db, "https://example.com/jobs/contoso-ai-integration")[0]
    assert "Strong written and spoken English" in contoso


def test_second_scan_does_not_show_the_same_postings(tmp_path, monkeypatch, capsys):
    db = store.connect(tmp_path / "t.db")
    monkeypatch.setattr(scan.store, "connect", lambda: db)
    scan.main([])
    capsys.readouterr()
    scan.main([])
    assert "already shown 4" in capsys.readouterr().out  # the 5th (PLC) is cut by the filter before "seen"
