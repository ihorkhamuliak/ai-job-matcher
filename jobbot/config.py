# Novelty is "not seen yet" (table `seen`); the window only cuts off dead postings.
# Older but still open postings are shown with their age on the card: the junior market is thin,
# and boards re-promote postings for weeks.
WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 30

# Scoring by the model: synchronous, prompt-cached, up to SCORE_CAP per day, freshest first inside a queue group.
# Model choice was measured, not guessed: scripts/model_bakeoff.py scores the same live postings that the previous
# model already scored. Haiku 5.5 came out ~12x cheaper ($0.00053 vs $0.0064 per posting) and ~0.6 points stricter;
# with the digest threshold at 5 it kept every posting the owner actually applied to (11 of 11) and lost no 8+.
# CV and cover-note generation stays on Sonnet: quality matters more there than cents.
SCORE_MODEL = "claude-haiku-5-5"
PACKAGE_MODEL = "claude-sonnet-5-5"
SCORE_CAP = 120
# A scan that starts at this hour (Warsaw time) is the evening one: it may use the full daily cap,
# the midday scan only half, so a missed midday scan does not eat half of the day.
EVENING_FROM = 17
DIGEST_TOP, DIGEST_MIN = 10, 5
# Old scores in the database keep the threshold of the model that produced them (Sonnet 5 ~ Haiku 4),
# otherwise switching models would flood the digest with yesterday's weak postings.
DIGEST_MIN_BY_MODEL = {"claude-sonnet-5-5": 6}
# Postings older than this are never sent to the model.
# Out of API credit -> instead of scored postings, NO_CREDIT_TOP clean ones without a score.
SCORE_MAX_DAYS = 20
NO_CREDIT_TOP = 5
# Money floor (PLN/month): below it no contract type reaches the owner's minimum; details in money.py
MONEY_FLOOR = 6000
# $ per 1M tokens (input, output)
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}

# Industrial automation (PLC, SCADA) shares the word "automation" with our field; it is not ours.
EXCLUDE_CATEGORIES = {"automation"}
EXCLUDE_TITLE = r"\b(plc|automatyk\w*|scada|sterownik\w*)\b"

# Source sensor: raw yield below this share of the 7-day median = yellow.
# Catches broken pagination (233 instead of ~1100) that a "zero results" check does not see.
YIELD_DROP_RATIO = 0.3
# A zero that the source proved (the site confirmed the filter) is shown as white, not red.
CONFIRMED_EMPTY = "0, filter confirmed by the site"
