# ai-job-matcher

**English** | [Українська](README.uk.md)

A personal job-search assistant I run every day while looking for an automation / AI role in Poland.
It reads new postings, filters them with plain code, lets an LLM score what is left against a bank of my real
experience, and sends a short digest to Telegram. One tap on a posting builds a one-page CV and a cover note for
that posting, using only facts from the bank.

This repository is the **core of the private version**. Job-board adapters are not included (see
[What is not here](#what-is-not-here)); a demo source with synthetic postings stands in for them, so every step
after the source is the code that runs in production.

## How it works

```
source (10 boards in the private version, examples/jobs.json here)
  -> dedup: one posting across cities and boards = one key
  -> sieve in code: window, industrial "automation", title blacklist, money floor
  -> rule-based marks: years of experience, English / Polish level, third language, office in another city
  -> queue: reachable postings first (remote, home city, Warsaw hybrid), daily cap, freshest first
  -> LLM score 1-10 against the facts bank, minus 1 per soft warning
  -> Telegram digest: one message per posting, buttons: not for me / applying
  -> "applying": CV (PDF, 1 page) + LinkedIn note + cover letter + gap questions, row in a Google Sheet
```

## Engineering decisions (measured, not guessed)

- **Rules in code, judgement in the model.** Anything deterministic (experience, languages, money, location) is
  decided by code before the model sees the posting. The model only scores how the tasks match my experience.
  Rules live in `jobbot/reqs.py`, `jobbot/money.py` and `jobbot/rank.py`, each one with the case that created it.
- **Model choice by bake-off.** `scripts/model_bakeoff.py` re-scores postings the previous model already scored.
  Claude Haiku 5.5 came out ~12x cheaper than Sonnet 5.5 ($0.00053 vs $0.0064 per posting) and ~0.6 points
  stricter. With the digest threshold at 5 it kept every posting I actually applied to (11 of 11) and lost no 8+.
  CV and letter generation stays on Sonnet, where quality matters more than cents.
- **The model may only choose.** For the CV it picks a summary variant, five headline skills and the order of facts
  from the bank. Code renders only what exists in the bank; a skill the posting wants but the bank lacks becomes a
  question in Telegram, and the answer goes back into the bank.
- **Check the output, not the input.** The PDF is verified by extracted text (one page, name present, GDPR clause
  for Polish CVs), not by looking at the HTML.
- **Sensors instead of hope.** Every scan sends a header even when there is nothing new (silence = the bot is down).
  The header shows sources that returned less than 30% of their 7-day median (broken pagination), postings left
  waiting under the daily cap, and scored cards with no reaction for 2+ days.
- **Tests carry the reason.** 151 tests, many named after the real posting or incident that produced the rule.

## Run the demo

```bash
pip install -r requirements.txt
python -m jobbot.scan --no-mark      # without a key: dedup, sieve and marks; scoring is skipped
cp .env.example .env                  # add ANTHROPIC_API_KEY to score the demo postings (a few tenths of a cent)
python -m pytest -q
```

For the CV part you need your own `facts.yaml` (see `tests/bank_fixture.yaml` for the shape), and the letter
templates and the name check in `jobbot/cv.py` use the placeholder name "Jan Kowalski".

The Telegram UI texts and the model prompts are in Ukrainian, my working language. Code comments are in English.

## What is not here

- **Job-board adapters.** Most Polish job boards forbid automated collection in their terms of service, so the code
  that reads them stays private and is used for my own job search only.
- **Contact search and the mailbox reader.** They process personal data of third parties.
- **My facts bank and CVs.** Personal data.

## Stack

Python 3.13 · Claude API (Haiku 5.5 for scoring, Sonnet 5.5 for CV choice) · SQLite · Telegram Bot API ·
Google Sheets API · WeasyPrint · Docker

License: MIT
