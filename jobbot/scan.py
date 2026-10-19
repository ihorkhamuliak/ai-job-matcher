"""One scan: source -> dedup -> rule-based marks -> model scoring -> digest.

The private version reads ten Polish job boards. Board adapters are not published: most boards forbid automated
collection in their terms of service. This public version reads synthetic postings from examples/jobs.json,
so every step after the source is the real code.
  python -m jobbot.scan [--tg] [--no-mark]"""
import argparse
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import config, filters, money, rank, reqs, store, tg
from .job import Job

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "jobs.json"


def demo_jobs(path: Path = EXAMPLES) -> list[Job]:
    """Synthetic postings. Each one carries its full text, like boards that return it in the listing."""
    now = time.time()
    return [Job(source="demo", title=d["title"], company=d["company"], url=d["url"],
                posted_at=now - d.get("age_days", 0) * 86400, country="PL", cities=d.get("cities", []),
                remote=d.get("mode") == "remote", mode=d.get("mode", ""), seniority=d.get("seniority", []),
                salary=d.get("salary", ""), text=d["text"])
            for d in json.loads(path.read_text(encoding="utf-8"))]


def merge(jobs: list[Job]) -> dict[str, Job]:
    """The same posting arrives once per city and from several queries: merge by key, keep the union of cities."""
    out: dict[str, Job] = {}
    for j in jobs:
        m = out.get(j.key)
        if m is None:
            out[j.key] = j
            continue
        m.cities = sorted(set(m.cities) | set(j.cities))
        m.remote = m.remote or j.remote
        m.posted_at = max(m.posted_at, j.posted_at)
        m.open_until = max(m.open_until, j.open_until)
        m.text = m.text or j.text
    return out


def main(argv: list[str] | None = None) -> None:
    started = rank.now_warsaw()
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.WINDOW_DAYS)
    ap.add_argument("--no-mark", action="store_true", help="do not mark shown postings as seen (dev runs)")
    ap.add_argument("--tg", action="store_true", help="send the digest with buttons to Telegram")
    args = ap.parse_args(argv)
    days = max(1, min(args.days, config.MAX_WINDOW_DAYS))

    db = store.connect()
    raw = demo_jobs()
    statuses = [("demo", "examples/jobs.json", *store.log_yield(db, "demo", "examples", len(raw), None))]
    merged = merge(raw)
    dropped, new = Counter(), []
    for j in merged.values():
        reason = filters.drop_reason(j, days)
        if reason is None and store.is_seen(db, j.key):
            reason = "already shown"
        if reason:
            dropped[reason] += 1
        else:
            new.append(j)
    new.sort(key=lambda j: j.posted_at, reverse=True)
    for j in new:
        if j.text and not store.text_row(db, j.url)[0]:
            store.save_text(db, j, j.text)
    texts = {j.url: store.text_row(db, j.url) for j in new}
    marks = {j.url: reqs.marks(j, texts[j.url][0]) for j in new}
    for j in new:
        if om := rank.office_mark(j, texts[j.url][0]):
            marks[j.url].append(om)
        if mm := money.mark(j.salary):
            marks[j.url].append(mm)
    ranked = rank.step(db, new, texts, marks)

    print(f"ai-job-matcher · {datetime.now():%d.%m %H:%M} · window {days} d\n")
    print(f"Raw {len(raw)} -> unique {len(merged)} · dropped: "
          + (" · ".join(f"{r} {n}" for r, n in dropped.most_common()) or "nothing"))
    r = ranked["routes"]
    print(f"Scoring ({config.SCORE_MODEL}): to model {r['model']} · heavy warnings {r['low']} · dropped by title "
          f"{r['drop']} · scored now {ranked['scored']} (${ranked['cost']:.3f})"
          + (f"\n  {ranked['note']}" if ranked["note"] else ""))
    print(f"\nDIGEST (score >= {config.DIGEST_MIN}, top {config.DIGEST_TOP}; -1 per warning): {len(ranked['digest'])}")
    for final, j, s in ranked["digest"]:
        print(f"\n  {final}/10  {j.title} · {j.company}\n     {s['why']}")
        if marks[j.url]:
            print("     " + " · ".join(marks[j.url]))
    if args.tg:
        sent = tg.send_scan(db, tg.Bot.from_env(), statuses, ranked, marks, started)
        print(f"\nTelegram: header + {sent} postings")
    if not args.no_mark:
        for j in new:
            store.mark_seen(db, j)


if __name__ == "__main__":
    main()
