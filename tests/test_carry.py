"""Cash is never idle, and a coupon is part of a bond's return.

Two promises the ledger makes about the time between two closes. A book's
uninvested cash earns the overnight Treasury bill rate the desk recorded, and a
holding is paid the distributions its provider reported, on the ex-date. Both are
arithmetic on the price book — no model, no estimate — which is what lets the
archive replay them to the cent (article 12).
"""
import json
import subprocess
import sys
from pathlib import Path


def run_day(company, date, day):
    env = {"MOCK_LLM": "1", "MOCK_HTTP": "1", "SHIFT_DATE": date,
           "MOCK_ANSWERS": str(company / "tests/mock_answers.json"),
           "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(company)}
    return subprocess.run([sys.executable, "kernel/runner.py", "--day", day],
                          cwd=company, env=env, capture_output=True, text=True)


def read(company, rel, default=None):
    path = Path(company) / rel
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def book_with(cash, positions=None):
    return {"cash": cash, "positions": positions or {}}


def prices(date, rate=None, quotes=None):
    out = {"date": date, "quotes": quotes or {}}
    if rate is not None:
        out["rates"] = {"TBILL3M": {"pct": rate, "asof": date}}
    return out


def test_idle_cash_earns_the_recorded_rate_for_every_calendar_day(logic):
    """Friday to Monday is three nights of interest, at Friday's rate, actual/360."""
    ledger = logic(Path(__file__).resolve().parents[1], "ledger")
    record = ledger.carry(book_with(100_000.0), "2026-09-04", prices("2026-09-04", 3.60),
                          "2026-09-07", prices("2026-09-07", 9.99))
    assert record["days"] == 3 and record["rate_pct"] == 3.60
    assert record["interest"] == round(100_000 * 0.036 * 3 / 360, 2) == 30.0


def test_with_no_rate_recorded_cash_earns_nothing_and_says_so(logic):
    ledger = logic(Path(__file__).resolve().parents[1], "ledger")
    record = ledger.carry(book_with(50_000.0), "2026-09-04", prices("2026-09-04"),
                          "2026-09-07", prices("2026-09-07"))
    assert record["interest"] == 0.0 and record["rate_pct"] is None


def test_a_price_book_from_before_rates_falls_back_to_todays_quote(logic):
    """The first night after this was introduced: yesterday's file has no rate."""
    ledger = logic(Path(__file__).resolve().parents[1], "ledger")
    record = ledger.carry(book_with(36_000.0), "2026-09-10", prices("2026-09-10"),
                          "2026-09-11", prices("2026-09-11", 3.838))
    assert record["rate_from"] == "today" and record["interest"] == round(36_000 * 0.03838 / 360, 2)


def test_a_distribution_is_paid_once_on_the_close_the_price_first_drops(logic):
    ledger = logic(Path(__file__).resolve().parents[1], "ledger")
    held = {"EMB": {"qty": 100.0, "cost": 9_000.0}}
    before = prices("2026-09-01", 4.0, {"EMB": {"close": 90.0, "asof": "2026-08-31"}})
    events = [{"ex_date": "2026-08-01", "amount": 0.40},     # already paid last month
              {"ex_date": "2026-09-01", "amount": 0.41},     # this one
              {"ex_date": "2026-10-01", "amount": 0.42}]     # not yet
    after = prices("2026-09-02", 4.0, {"EMB": {"close": 89.6, "asof": "2026-09-01",
                                               "distributions": events}})
    record = ledger.carry(book_with(0.0, held), "2026-09-01", before, "2026-09-02", after)
    assert [d["ex_date"] for d in record["distributions"]] == ["2026-09-01"]
    assert record["distributions"][0]["amount"] == 41.0
    # The next night the same event is still in the provider's window. It is not
    # paid twice, because the close it belongs to is behind the book now.
    later = prices("2026-09-03", 4.0, {"EMB": {"close": 89.7, "asof": "2026-09-02",
                                               "distributions": events}})
    again = ledger.carry(book_with(0.0, held), "2026-09-02", after, "2026-09-03", later)
    assert again["distributions"] == []


def test_a_book_is_paid_once_however_often_the_day_is_rerun(company, logic):
    ledger = logic(company, "ledger")
    ledger.mark(company, "careful", {}, "2026-09-04")
    (company / "company/data/prices").mkdir(parents=True, exist_ok=True)
    (company / "company/data/prices/2026-09-04.json").write_text(
        json.dumps(prices("2026-09-04", 4.0)), encoding="utf-8")
    first = ledger.accrue(company, "careful", "2026-09-07", prices("2026-09-07", 4.0))
    second = ledger.accrue(company, "careful", "2026-09-07", prices("2026-09-07", 4.0))
    assert first["credited"] == round(100_000 * 0.04 * 3 / 360, 2) and second is None
    book = read(company, "company/data/portfolios/careful.json")
    assert book["cash"] == round(100_000 + first["credited"], 2)


def test_the_rate_is_quoted_and_recorded_like_a_price(company, logic, monkeypatch):
    market = logic(company, "market")
    monkeypatch.setenv("MOCK_HTTP", "1")
    book = market.prices(company, "2026-09-04")
    assert book["rates"]["TBILL3M"]["pct"] == 4.12
    assert "TBILL3M" not in book["quotes"], "a rate is read by the ledger, never traded"


def test_yahoo_dividends_are_read_on_their_ex_date(logic):
    market = logic(Path(__file__).resolve().parents[1], "market")
    body = json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": 93.69},
        "events": {"dividends": {"1788269400": {"amount": 0.414, "date": 1788269400}}}}]}})
    assert market._yahoo_distributions(body) == [{"ex_date": "2026-09-01", "amount": 0.414}]


def test_fred_reads_the_last_row_that_has_a_value(logic):
    market = logic(Path(__file__).resolve().parents[1], "market")
    body = "observation_date,DTB3\n2026-09-08,3.84\n2026-09-09,3.83\n2026-09-10,.\n"
    assert market._read_fred_csv(body) == (3.83, "2026-09-09")


def test_every_book_is_paid_overnight_and_the_archive_replays_it(company, logic):
    """End to end: interest and a distribution land in the book, the income file,
    the minutes and the advisor's prompt — and replaying the record reproduces
    every published NAV to the cent, which is the only proof that counts."""
    assert run_day(company, "2026-09-04", "fri").returncode == 0
    held = {}
    for path in (company / "company/data/portfolios").glob("*.json"):
        book = json.loads(path.read_text(encoding="utf-8"))
        if path.stem != "benchmark":
            for symbol in book["positions"]:
                held.setdefault(symbol, path.stem)
    assert held, "the fixture day bought nothing to be paid on"
    symbol, owner = sorted(held.items())[0]
    mock = json.loads((company / "tests/mock_prices.json").read_text(encoding="utf-8"))
    mock[symbol] = {"close": mock[symbol],
                    "distributions": [{"ex_date": "2026-09-05", "amount": 1.25}]}
    (company / "tests/mock_prices.json").write_text(json.dumps(mock), encoding="utf-8")
    assert run_day(company, "2026-09-07", "mon").returncode == 0

    income = read(company, "company/data/income/2026-09-07.json")
    paid = income["books"][owner]
    assert paid["days"] == 3 and paid["rate_pct"] == 4.12 and paid["interest"] > 0
    assert [d["instrument"] for d in paid["distributions"]] == [symbol]
    assert "benchmark" in income["books"]
    assert "Paid overnight" in (company / "company/minutes/2026-09-07-desk.md").read_text(
        encoding="utf-8")

    replay = logic(company, "replay")
    for key in [p.stem for p in (company / "company/data/nav").glob("*.json")]:
        published = [r["nav"] for r in read(company, f"company/data/nav/{key}.json")["series"]]
        if key == "benchmark":
            _, rows = replay.buy_and_hold(company)
        else:
            _, rows = replay.replay_advisor(company, key)
        assert [r["nav"] for r in rows] == published, key
