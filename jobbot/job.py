import re
from dataclasses import dataclass, field


_GENDER = re.compile(r"\((?:[kmfwdnxż]\s*[/|]\s*)+[kmfwdnxż]\)|\b[kmf]\s*/\s*[kmf](?:\s*/\s*[a-zż])?\b"
                     r"|\s*/\s*-?ka\b")
_PAIR = re.compile(r"\b(\w{4,})(\w*)\s*/\s*\1\w*")  # «Kierownik / Kierowniczka» → «Kierownik»


def _norm(s: str) -> str:
    """Gender forms and punctuation do not turn one posting into two: 'Engineer (K/M)' = 'Engineer/-ka' (the same company on two
    boards), 'Engineer / MLOps' = 'Engineer/ MLOps'. Measured on the 02.10 listings: 39 cross-board groups (03.10)."""
    s = _PAIR.sub(r"\1\2", _GENDER.sub(" ", s.lower()))
    return " ".join(re.sub(r"\W+", " ", s).split())


def mode_of(remote: bool, hybrid: bool, office: bool) -> str:
    """Site work-mode field -> Job.mode. Board values were taken from a live run on 06.10."""
    return "remote" if remote else "hybrid" if hybrid else "office" if office else ""


@dataclass
class Job:
    source: str
    title: str
    company: str
    url: str
    posted_at: float  # unix, seconds
    # No default: a default of 'PL' let Hungary through on 28.09.
    # Every source must name the country explicitly.
    country: str
    cities: list[str] = field(default_factory=list)
    remote: bool = False
    # The most flexible mode the posting allows: remote / hybrid / office; '' = the site does not say (then we read the text).
    # An office posting without a single word about it in the text got 9/10 without a warning on 06.10 (workplaceType=office)
    mode: str = ""
    seniority: list[str] = field(default_factory=list)
    category: str = ""
    salary: str = ""
    # 'Open until', if the site says so itself (unix). While in the future, the window does not cut: one board keeps
    # a posting ~62 days with extensions (owner decision 29.09). 0 = the site does not say, the window applies.
    open_until: float = 0.0
    # Full text, if the listing returns it itself (some boards do). The rest is fetched separately (not published).
    text: str = ""

    @property
    def key(self) -> str:
        """One posting from different cities and different boards = one key (D6 from bytecoder0x)."""
        return f"{_norm(self.title)}|{_norm(self.company)}"
