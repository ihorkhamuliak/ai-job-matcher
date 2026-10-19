import re
import time

from . import config
from .job import Job

_EXCLUDE_TITLE = re.compile(config.EXCLUDE_TITLE, re.IGNORECASE)


def location_ok(job: Job) -> bool:
    """Poland: any city. Other countries: remote only.
    
    Office or hybrid in Poland is not visible from board listings; it is resolved from the full text (step 2)."""
    return job.country == "PL" or job.remote


def drop_reason(job: Job, window_days: int, now: float | None = None) -> str | None:
    now = now or time.time()
    if now - job.posted_at > window_days * 86400 and job.open_until <= now:
        return "старше вікна"
    if job.category in config.EXCLUDE_CATEGORIES or _EXCLUDE_TITLE.search(job.title):
        return "промислова автоматика"
    if not location_ok(job):
        return "локація"
    return None
