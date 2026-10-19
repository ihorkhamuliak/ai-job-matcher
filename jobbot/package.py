"""Package for one posting (step 4, owner decision 10.10): box button -> the model chooses from the bank -> CV as PDF + connection note
and cover letter + gap questions. Answer 🔧/👌 -> the CV is rebuilt without the model (the choice is stored)."""
import re
import time

from . import config, cv, rank, store

OUT = rank.ROOT / "data" / "packages"


def _files(choice: dict, b: dict, meta: dict, url: str) -> dict:
    """HTML -> PDF -> check by extracted text; a copy goes to the archive (the exact version the employer saw)."""
    for font in cv.FONTS:  # 1 page guaranteed: font steps down (owner decision 10.10)
        page = cv.render(b, choice, font)
        data, pages = cv.pdf(page)
        if pages == 1:
            break
    else:
        raise RuntimeError(f"CV не влазить в 1 сторінку навіть на {cv.FONTS[-1]}pt")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", meta.get("company") or url.split("/")[2]).strip("_")[:40] or "job"
    name = f"Jan_Kowalski_CV_{slug}"
    OUT.mkdir(parents=True, exist_ok=True)
    # 19.10: the file in the folder has the same name the recruiter sees (the owner uploaded the dated archive name to a form).
    # First HTML line = URL: a rebuild of the same posting overwrites, another posting of the same company gets _2
    head, n = f"<!-- {url} -->\n", 1
    while (OUT / f"{name}.html").exists() and not (OUT / f"{name}.html").read_text(encoding="utf-8").startswith(head):
        n += 1
        name = f"Jan_Kowalski_CV_{slug}_{n}"
    (OUT / f"{name}.html").write_text(head + page, encoding="utf-8")
    (OUT / f"{name}.pdf").write_bytes(data)
    return {"pdf": data, "filename": f"{name}.pdf", "problems": cv.check_pdf(data, page)}


def archive(age: float = 3600) -> None:
    """19.10 (owner: the folder fills up, I already applied): a package older than an hour -> archive/ with the date in front.
    A laptop-side sync (not published) sees only the root, so the file moves to the archive there too. Already dated files keep one date."""
    if not OUT.exists():
        return
    for f in [*OUT.glob("*.pdf"), *OUT.glob("*.html")]:
        t = f.stat().st_mtime
        if time.time() - t < age:
            continue
        (OUT / "archive").mkdir(exist_ok=True)
        dest = OUT / "archive" / (f.name if re.match(r"\d{8}_", f.name) else f"{time.strftime('%Y%m%d', time.localtime(t))}_{f.name}")
        if dest.exists():  # same company on the same day, already in the archive
            dest = dest.with_name(f"{time.strftime('%H%M', time.localtime(t))}_{dest.name}")
        f.replace(dest)


def build(db, url: str, client) -> dict:
    meta, text = store.sent_meta(db, url), store.text_row(db, url)[0]
    if not text:
        raise RuntimeError("нема тексту вакансії в базі")
    b = cv.load(store.answers(db))
    raw, usage = cv.choose(client, b, meta.get("title", ""), meta.get("company", ""), text)
    choice = cv.validate(b, raw)
    store.save_package(db, url, choice, raw)
    gaps = [(store.add_gap(db, url, g["skill"], g["category"]), g["skill"]) for g in cv.gaps(b, raw)]
    subject, body = cv.letter(raw, choice["lang"], meta.get("title", ""), meta.get("source", ""))
    note = cv.clean(raw["note"])
    return {**_files(choice, b, meta, url), "lang": choice["lang"], "note": note, "subject": subject, "body": body,
            "gaps": gaps,
            "cost": rank.cost(config.PACKAGE_MODEL, usage)}


def rebuild(db, url: str) -> dict:
    """After a gap answer: the same choice, the bank with the new answer. 'Basics' this posting asked for
    are added to the Basics line."""
    choice, raw = store.package(db, url)
    asked = [s for s, lvl in db.execute("SELECT skill, level FROM gaps WHERE url = ? AND level = 'basics'", (url,))]
    choice = {**choice, "basics": choice["basics"] + [s for s in asked if s not in choice["basics"]]}
    meta = store.sent_meta(db, url)
    body = cv.letter(raw, choice["lang"], meta.get("title", ""), meta.get("source", ""))[1]  # the signature is rebuilt with the letter
    return {**_files(choice, cv.load(store.answers(db)), meta, url), "body": body}
