"""Model bake-off (owner decision 19.10, 'the API is expensive'): Haiku 5.5 is ~20x cheaper than Sonnet 5.5 by list price, caching from
512 tokens (on 03.10 Haiku 4.5 lost precisely on caching and price). Sonnet already scored these postings - Haiku scores the same texts,
and we compare with the stored model score (before the code penalty). Sample: ALL postings Sonnet scored 6+ (the point is not to lose them) + N lower.
  python scripts/model_bakeoff.py [lower=30]"""
import json
import random
import sqlite3
import sys

import anthropic

from jobbot import config, rank
from jobbot.job import Job

HAIKU = "claude-haiku-5-5"
config.PRICES.setdefault(HAIKU, (0.10, 0.50))  # price list from the claude-api reference, cached 06.10.2026
N = int(sys.argv[1]) if len(sys.argv) > 1 else 30
db = sqlite3.connect("file:/app/data/jobs.db?mode=ro", uri=True)
rows = db.execute("SELECT s.url, s.score, se.title, se.company, se.source, t.text FROM scores s "
                  "JOIN texts t ON t.url = s.url JOIN seen se ON se.url = s.url "
                  "WHERE s.model = 'claude-sonnet-5-5' AND t.text != ''").fetchall()
high = [r for r in rows if r[1] >= 6]
random.seed(19)
sample = high + random.sample([r for r in rows if r[1] < 6], min(N, len(rows) - len(high)))
client, facts = anthropic.Anthropic(api_key=rank.api_key()), rank.facts_text()
# First run 19.10: 30 of 85 = stop_reason max_tokens (Haiku 5.5 thinks adaptively, 1024 is not enough),
# mostly 6+ -> a skewed sample. Here the limit is 4096 through a create wrapper; rank.score is not touched
_create = client.messages.create
client.messages.create = lambda **kw: _create(**{**kw, "max_tokens": 4096})
spent, tok, out, errors = 0.0, {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}, [], 0
for url, s_score, title, company, source, text in sample:
    job = Job(source, title, company, url, 0, "PL")
    try:
        data, usage = rank.score(client, HAIKU, job, text, facts)
    except Exception as e:
        errors += 1
        print("ПОМИЛКА", title[:50], type(e).__name__, str(e)[:120])
        continue
    spent += rank.cost(HAIKU, usage)
    for k in usage:
        tok[k] += usage[k]
    out.append((s_score, data["score"], title, company, data.get("why", ""), url))
out.sort(key=lambda r: -abs(r[0] - r[1]))
print(f"вибірка {len(sample)}: Sonnet 6+ {len(high)}, нижчих {len(sample) - len(high)}; помилок {errors}\n")
for s, h, title, company, why, url in out:
    if abs(s - h) >= 2:
        print(f"Sonnet {s} · Haiku {h} · {title[:60]} · {company[:25]}\n   H: {why[:220]}\n   {url}")
lost = [r for r in out if r[0] >= 6 and r[1] < 6]
found = [r for r in out if r[0] < 6 and r[1] >= 6]
print(f"\nрозбіжність ≥2: {sum(abs(s - h) >= 2 for s, h, *_ in out)} з {len(out)} · "
      f"Sonnet 6+ → Haiku <6 (втрачені): {len(lost)} з {sum(r[0] >= 6 for r in out)} · Sonnet <6 → Haiku 6+ (зайві): {len(found)}")
for t in (5, 6):
    lost_t = [r for r in out if r[0] >= 6 and r[1] < t]
    print(f"поріг Haiku ≥{t}: втрачено {len(lost_t)} з {sum(r[0] >= 6 for r in out)} Sonnet 6+ "
          f"(з них 8+: {sum(r[0] >= 8 for r in lost_t)}), зайвих {sum(1 for r in out if r[0] < 6 and r[1] >= t)}")
for s, h, title, company, *_ in sorted(lost, key=lambda r: -r[0]):
    print(f"   втрачено: Sonnet {s} · Haiku {h} · {title[:55]} · {company[:20]}")
# The main yardstick is the owner's decisions: box (applied) and thumbs-down with a reason, not the Sonnet score
acts = dict(db.execute("SELECT url, kind FROM actions"))
for kind in ("applied", "dislike"):
    rs = [r for r in out if acts.get(r[5]) == kind]
    print(f"{'📦 подався' if kind == 'applied' else '👎'} ({len(rs)}): " + " · ".join(
        f"{c[:14]} S{s}/H{h}" for s, h, _, c, *_ in sorted(rs, key=lambda r: -r[0])))
print(f"середнє: Sonnet {sum(r[0] for r in out) / len(out):.2f} · Haiku {sum(r[1] for r in out) / len(out):.2f}")
print(f"Haiku 5.5: ${spent:.4f} за {len(out)} = ${spent / max(len(out), 1):.5f}/вак. "
      f"(Sonnet записаний: ${db.execute('SELECT AVG(cost) FROM scores WHERE model = ?', ('claude-sonnet-5-5',)).fetchone()[0]:.5f}/вак.)")
print("токени Haiku:", json.dumps(tok))
