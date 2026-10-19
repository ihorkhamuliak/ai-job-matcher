"""Applications sheet (step 5b, owner decision 10.10): applying appends a row, the undo button removes it (from 12.10 completely,
even if edited: owner 11.10).
The sheet is the source of truth. Access: a copy of an existing Google OAuth credential in .env, so the automation
that already uses it is never restarted."""
import time
from datetime import date
from urllib.parse import quote

import httpx

TAB = "Подачі"
# A..P, as in the sheet on 06.10. None = the cell is not touched (the Sheets API skips null): M is an ARRAYFORMULA 'days waiting'
HEAD = ["Дата", "Компанія", "Роль", "Місто / режим", "Посилання", "Джерело", "Бал бота", "CV", "Крок 6", "Етап",
        "Відповідь", "Дата відповіді", "Днів чекання", "Дата співбесіди", "Нотатки", "Група"]
GROUP = "тест 10"  # while the 10-applications test runs (owner decision 10.10)


def shown_company(name: str, source: str) -> str:
    """OLX gives a profile name, not the employer (12.10) - so we write exactly that. Display only: the dedup key, contact
    search and the letter take the name as the site gave it, otherwise every OLX posting would become 'new' and the suffix would leak."""
    return f"{name} (профіль OLX)" if source in ("olx", "olx.pl") else name


def note(meta: dict) -> str:
    return f"бракує: {', '.join(meta['missing'][:4])}" if meta.get("missing") else ""


def row(url: str, meta: dict, today: date) -> list:
    v = dict.fromkeys(HEAD)
    v.update({"Дата": (today - date(1899, 12, 30)).days,
              "Компанія": shown_company(meta.get("company", ""), meta.get("source", "")),
              "Роль": meta.get("title", ""), "Місто / режим": meta.get("where", ""), "Посилання": url,
              "Джерело": meta.get("source", ""), "Бал бота": meta.get("score", ""),
              "CV": (meta.get("pkg") or {}).get("cv"), "Етап": "подано",  # 12.10: 'PL · bot' from the package (language · type)
              "Нотатки": note(meta), "Група": GROUP})
    return [v[h] for h in HEAD]


class Sheet:
    def __init__(self, sheet_id: str, client_id: str, secret: str, refresh: str, http=None):
        self.id, self._creds = sheet_id, {"client_id": client_id, "client_secret": secret, "refresh_token": refresh,
                                          "grant_type": "refresh_token"}
        self.http = http or httpx.Client(timeout=30)
        self._token, self._until = None, 0.0

    @classmethod
    def from_env(cls, env) -> "Sheet | None":
        vals = [env(k) for k in ("PODACHI_SHEET", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")]
        return cls(*vals) if all(vals) else None

    def _api(self, method: str, path: str, body=None) -> dict:
        if time.time() > self._until:
            r = self.http.post("https://oauth2.googleapis.com/token", data=self._creds).json()
            self._token, self._until = r["access_token"], time.time() + r.get("expires_in", 3600) - 300
        r = self.http.request(method, f"https://sheets.googleapis.com/v4/spreadsheets/{self.id}{path}", json=body,
                              headers={"Authorization": f"Bearer {self._token}"})
        if r.status_code >= 400:
            raise RuntimeError(f"Sheets {r.status_code}: {r.text[:150]}")
        return r.json()

    def _rows(self) -> list[list]:
        return self._api("GET", f"/values/{quote(TAB + '!A1:P1000', safe='')}").get("values", [])

    def find(self, url: str, vals: list[list] | None = None) -> tuple[int, dict] | None:
        """(row number from 1, {column: value}) by the address in the 'Link' column."""
        col = HEAD.index("Посилання")
        for i, r in enumerate((vals if vals is not None else self._rows())[1:], start=2):
            if len(r) > col and r[col] == url:
                return i, dict(zip(HEAD, r + [""] * (len(HEAD) - len(r))))
        return None

    def append(self, url: str, meta: dict, today: date) -> tuple[int, bool]:
        """(row, new?). The address is already there - no duplicate. Not values:append: the ARRAYFORMULA in M yields 'empty'
        values down to row 1000, and the row could land on 1001 - we compute the row ourselves from the 'Date' column."""
        vals = self._rows()
        if found := self.find(url, vals):
            return found[0], False
        n = max((i for i, r in enumerate(vals, start=1) if r and r[0]), default=1) + 1
        self._api("PUT", f"/values/{quote(f'{TAB}!A{n}:P{n}', safe='')}?valueInputOption=RAW",
                  {"values": [row(url, meta, today)]})
        return n, True

    def remove(self, url: str) -> str:
        """removed / absent."""
        if not (found := self.find(url)):
            return "absent"
        n = found[0]
        gid = next(s["properties"]["sheetId"] for s in self._api("GET", "?fields=sheets.properties")["sheets"]
                   if s["properties"]["title"] == TAB)
        self._api("POST", ":batchUpdate", {"requests": [{"deleteDimension": {"range": {
            "sheetId": gid, "dimension": "ROWS", "startIndex": n - 1, "endIndex": n}}}]})
        return "removed"
