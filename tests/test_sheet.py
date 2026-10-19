"""Step 5b, 10.10: applications sheet (owner decision: applying -> a row, undo removes it, the sheet is the source of truth). No network."""
import types
from datetime import date

from jobbot import sheet as sh

URL = "https://x/acme"
META = {"title": "Młodszy Specjalista AI", "company": "Acme Sp. z o.o.", "where": "Poznań · офіс", "source": "pracuj.pl",
        "score": 9, "missing": ["Excel", "BaseLinker"]}


def live_rows():
    """As in the live sheet: header, 2 applications, then 'empty' ARRAYFORMULA values in M down to 1000 rows."""
    head = [sh.HEAD]
    data = [["06.10.2026", "TMS", "Asystent", "Gdańsk", "https://x/tms", "rocketjobs", "9", "", "", "подано", "", "",
             "4", "", "", "тест 10"],
            ["06.10.2026", "Fabrikam", "Informatyk", "", "https://x/fabrikam", "OLX", "9", "", "", "не подавались"]]
    return head + data + [[""] * 13 for _ in range(997)]


class FakeGoogle:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def _resp(self, body):
        return types.SimpleNamespace(status_code=200, json=lambda: body, text="")

    def post(self, url, data=None):
        return self._resp({"access_token": "t", "expires_in": 3600})

    def request(self, method, url, json=None, headers=None):
        self.calls.append((method, url, json))
        if method == "GET" and "fields=sheets.properties" in url:
            return self._resp({"sheets": [{"properties": {"sheetId": 1, "title": "Зведення"}},
                                          {"properties": {"sheetId": 555, "title": "Подачі"}}]})
        if method == "GET":
            return self._resp({"values": self.rows})
        return self._resp({})

    def writes(self):
        return [(m, u, j) for m, u, j in self.calls if m != "GET"]


def sheet(rows):
    return sh.Sheet("ID", "cid", "sec", "ref", http=FakeGoogle(rows))


def test_new_row_goes_under_last_dated_row_not_1001_and_skips_formula_column():
    s = sheet(live_rows())
    assert s.append(URL, META, date(2026, 10, 10)) == (4, True)
    (method, url, body), = s.http.writes()
    assert method == "PUT" and "A4%3AP4" in url and "valueInputOption=RAW" in url
    v = dict(zip(sh.HEAD, body["values"][0]))
    assert v["Дата"] == 46305 and v["Компанія"] == "Acme Sp. z o.o." and v["Посилання"] == URL and v["Бал бота"] == 9
    assert v["Етап"] == "подано" and v["Група"] == "тест 10" and v["Нотатки"] == "бракує: Excel, BaseLinker"
    assert all(v[c] is None for c in ("CV", "Крок 6", "Відповідь", "Дата відповіді", "Днів чекання", "Дата співбесіди"))


def test_same_link_twice_gives_no_duplicate():
    s = sheet(live_rows())
    assert s.append("https://x/tms", META, date(2026, 10, 10)) == (2, False)
    assert s.http.writes() == []


def untouched_row():
    rows = live_rows()
    rows[3] = ["46305", "Acme Sp. z o.o.", "Młodszy Specjalista AI", "Poznań · офіс", URL, "pracuj.pl", "9", "", "",
               "подано", "", "", "0", "", "бракує: Excel, BaseLinker", "тест 10"]
    return rows


def test_undo_deletes_row_even_if_ihor_already_edited_it():
    """12.10 (owner 11.10): undo removes the row completely, not only an untouched one."""
    for col, val in (("Етап", "подано"), ("Етап", "відповіли"), ("CV", "Automation PL"), ("Нотатки", "мої нотатки")):
        rows = untouched_row()
        rows[3][sh.HEAD.index(col)] = val
        s = sheet(rows)
        assert s.remove(URL) == "removed", col
        (method, url, body), = s.http.writes()
        assert body == {"requests": [{"deleteDimension": {"range": {"sheetId": 555, "dimension": "ROWS",
                                                                     "startIndex": 3, "endIndex": 4}}}]}
    assert sheet(live_rows()).remove(URL) == "absent"


def test_cv_column_comes_from_the_package():
    v = dict(zip(sh.HEAD, sh.row(URL, {**META, "pkg": {"chat": 1, "msg": 2, "cv": "PL · бот"}}, date(2026, 10, 12))))
    assert v["CV"] == "PL · бот" and v["Компанія"] == "Acme Sp. z o.o."


def test_olx_company_goes_to_sheet_as_profile_name():
    v = dict(zip(sh.HEAD, sh.row(URL, {**META, "company": "AGENCJA", "source": "olx.pl"}, date(2026, 10, 12))))
    assert v["Компанія"] == "AGENCJA (профіль OLX)"
