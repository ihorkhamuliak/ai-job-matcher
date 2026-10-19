"""package.py, 10.10: one CV came out on 2 pages - now the font steps down instead of sending it with a warning."""
from pathlib import Path

import pytest

from jobbot import cv, package, store


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "BANK", Path(__file__).with_name("bank_fixture.yaml"))
    monkeypatch.setattr(package, "OUT", tmp_path / "packages")
    monkeypatch.setattr(cv, "check_pdf", lambda data, page: [])
    db = store.connect(tmp_path / "t.db")
    store.mark_sent(db, "https://x/0", 7, meta={"company": "Contoso"})
    b = cv.load()
    store.save_package(db, "https://x/0", cv.default_choice(b, "pl"), {"tech": "n8n", "sentence": "zrobiłem X."})
    return db


def fake_pdf(fits_from):
    """1 page only when the font <= fits_from."""
    def pdf(page):
        size = float(page.split("font-size: ")[1].split("pt")[0])
        return f"PDF {size}".encode(), 1 if size <= fits_from else 2
    return pdf


def test_two_pages_step_font_down_until_one(env, monkeypatch):
    monkeypatch.setattr(cv, "pdf", fake_pdf(9.3))
    p = package.rebuild(env, "https://x/0")
    assert p["pdf"] == b"PDF 9.3" and p["filename"] == "Jan_Kowalski_CV_Contoso.pdf"
    assert "font-size: 9.3pt" in next(package.OUT.glob("*.html")).read_text(encoding="utf-8")


def test_already_one_page_keeps_v4_font(env, monkeypatch):
    monkeypatch.setattr(cv, "pdf", fake_pdf(9.6))
    assert package.rebuild(env, "https://x/0")["pdf"] == b"PDF 9.6"


def test_never_fits_is_an_error_not_a_two_page_cv(env, monkeypatch):
    monkeypatch.setattr(cv, "pdf", fake_pdf(8.0))
    with pytest.raises(RuntimeError, match="1 сторінку"):
        package.rebuild(env, "https://x/0")


def test_file_in_folder_has_the_name_recruiter_sees_and_second_job_of_same_firm_gets_2(env, monkeypatch):
    """19.10: the folder received a dated archive name, and the owner uploaded exactly that file to an application form."""
    monkeypatch.setattr(cv, "pdf", fake_pdf(9.6))
    package.rebuild(env, "https://x/0")
    package.rebuild(env, "https://x/0")  # a rebuild of the same posting overwrites instead of creating _2
    store.mark_sent(env, "https://x/1", 8, meta={"company": "Contoso"})
    store.save_package(env, "https://x/1", *store.package(env, "https://x/0"))
    package.rebuild(env, "https://x/1")
    assert sorted(f.name for f in package.OUT.glob("*.pdf")) == [
        "Jan_Kowalski_CV_Contoso.pdf", "Jan_Kowalski_CV_Contoso_2.pdf"]


def test_archive_moves_files_older_than_an_hour_with_date_once(tmp_path, monkeypatch):
    import os, time
    monkeypatch.setattr(package, "OUT", tmp_path)
    old = time.time() - 2 * 3600
    for name, t in (("Jan_Kowalski_CV_A.pdf", old), ("Jan_Kowalski_CV_A.html", old),
                    ("20261010_Fabrikam_en.pdf", old), ("Jan_Kowalski_CV_B.pdf", time.time())):
        (tmp_path / name).write_bytes(b"x")
        os.utime(tmp_path / name, (t, t))
    package.archive()
    day = time.strftime("%Y%m%d", time.localtime(old))
    assert sorted(f.name for f in tmp_path.glob("*.*")) == ["Jan_Kowalski_CV_B.pdf"]
    assert sorted(f.name for f in (tmp_path / "archive").iterdir()) == [
        "20261010_Fabrikam_en.pdf", f"{day}_Jan_Kowalski_CV_A.html", f"{day}_Jan_Kowalski_CV_A.pdf"]
