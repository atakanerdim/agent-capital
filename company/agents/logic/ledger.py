"""The book: what each advisor owns, what it is worth, and what it was worth.

Everything on the public site is read off these files, so two properties matter
more than anything clever this module could do.

**Valuation never needs a model.** Marking a book to market is arithmetic over a
price file. It runs whether or not a single language model answered today, which
is the difference between a desk that goes quiet for a week and one that does
not. The advisors are the part that can fail; the number on the page is not.

**A day is written once.** `mark()` is idempotent: run it twice for the same date
and the series has one entry for that date, carrying the later valuation. A shift
that is re-run by hand — and shifts here are re-run by hand, because the schedule
has been observed to skip a day without saying so — must not double-count.

Positions carry `cost` as well as `qty` so the site can show what a holding has
actually done, and so an advisor reading its own book tomorrow sees what it paid
rather than only what it holds. Cost is reduced proportionally on a partial sell:
selling half a position halves its cost, which keeps the remaining cost basis
honest without pretending to know whether the shares sold were the early ones.
"""
import copy
import datetime as dt
import json
from pathlib import Path

OPENING_CASH = 100_000.0

# The thing every advisor is actually competing with.
#
# A return means nothing on its own. Eight advisors all down 5% in a year the
# market fell 8% is eight good years; the same eight numbers in a year the market
# rose 20% is a desk that should not exist. Ranking advisors only against each
# other cannot tell those two years apart, and the difference is the entire
# question the desk was opened to answer.
#
# So: one more book, opened the same day with the same money, holding every
# instrument the desk may touch in equal weight, and never traded again. It is
# valued every day by the same `mark()` as everybody else — not by a separate
# formula written later, which is how a benchmark quietly becomes flattering.
#
# It is deliberately not an advisor. It holds every instrument that was on the list
# the day it opened (27 of them; later additions are not bought) where an advisor
# may hold 12, and it is never screened by risk. That is not an unfairness to
# correct; it is the comparison itself — a constrained active book against the
# unconstrained market. And it can only be opened on the desk's first day, because
# its opening prices are the first day's prices. There is no way to add it later
# that is not a backfill.
BENCHMARK_ID = "benchmark"
BENCHMARK_NAME = "Buy and hold"
BENCHMARK_MANDATE = ("Every instrument on the list the day the desk opened, equal "
                     "weight, bought on the first day and never traded again.")

# Cash is never idle.
#
# No investor leaves money in a drawer. A book's uninvested dollars sit, overnight,
# where a treasurer would put them: in the shortest US government paper, earning
# its rate. The rate is not written here and not chosen by anybody. It is quoted
# every morning like a price, from the providers `universe.json` names under
# "rates", recorded in the day's price book, and the interest is arithmetic on
# that record — which is what lets the archive replay it to the cent.
#
# Distributions are the other half. A bond fund earns most of its return as a
# monthly coupon and its price barely moves; counting price alone would have made
# every bond on the list a losing trade against a cash sweep that pays interest.
# So the dividends a provider reports travel into the price book beside the close,
# and a holder is credited on the ex-date, the same day the price drops by it.
SWEEP_RATE = "TBILL3M"
DAY_COUNT = 360           # money-market convention: actual days over 360


def _day(iso):
    return dt.date.fromisoformat(str(iso)[:10])


def carry(book, since, since_book, date, today_book):
    """What holding `book` from the close of `since` to the close of `date` paid.

    `since_book` and `today_book` are the two days' price books (the whole files:
    quotes and rates). Nothing here fetches and nothing is estimated:

    * **interest** on the cash that was in the book, for the calendar days between
      the two valuations, at the sweep rate recorded on `since` — the rate in force
      when the money was left overnight. A price book written before rates were
      recorded falls back to today's quote; with no rate recorded at all the
      interest is zero and the record says why, rather than borrowing a number.
    * **distributions** on every holding, for each ex-date the provider reported
      that falls after the close the book was last valued at and no later than the
      close it is valued at now. Keyed on each quote's own `asof`, so a dividend is
      credited on the same close that the price first drops by it.

    Returns a record; `apply_carry` puts it through the book.
    """
    out = {"since": since, "date": date, "days": 0, "cash_before": round(book.get("cash", 0.0), 2),
           "rate_pct": None, "rate_from": None, "interest": 0.0, "distributions": []}
    if not since or not since_book or str(since) >= str(date):
        return out
    days = (_day(date) - _day(since)).days
    out["days"] = days
    for label, source in (("since", since_book), ("today", today_book)):
        pct = (((source or {}).get("rates") or {}).get(SWEEP_RATE) or {}).get("pct")
        if isinstance(pct, (int, float)) and pct >= 0:
            out["rate_pct"], out["rate_from"] = float(pct), label
            break
    cash = float(book.get("cash", 0.0))
    if out["rate_pct"] is not None and cash > 0 and days > 0:
        out["interest"] = round(cash * out["rate_pct"] / 100.0 * days / DAY_COUNT, 2)
    before = (since_book or {}).get("quotes") or {}
    now = (today_book or {}).get("quotes") or {}
    for symbol, held in sorted((book.get("positions") or {}).items()):
        quote = now.get(symbol) or {}
        low = (before.get(symbol) or {}).get("asof") or str(since)
        high = quote.get("asof") or str(date)
        for event in quote.get("distributions") or []:
            ex = str(event.get("ex_date", ""))[:10]
            amount = event.get("amount")
            if not ex or not isinstance(amount, (int, float)) or amount <= 0:
                continue
            if low < ex <= high:
                out["distributions"].append({
                    "instrument": symbol, "ex_date": ex, "per_unit": float(amount),
                    "qty": held["qty"], "amount": round(held["qty"] * float(amount), 2)})
    return out


def apply_carry(book, record):
    """Credit a carry record to the book's cash. Returns the total credited."""
    total = round(record["interest"] + sum(d["amount"] for d in record["distributions"]), 2)
    book["cash"] = round(float(book.get("cash", 0.0)) + total, 2)
    book["carried_to"] = record["date"]
    return total


def _read(path, default):
    p = Path(path)
    if not p.exists():
        return copy.deepcopy(default)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(default)


def _write(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def portfolio_path(root, advisor):
    return Path(root) / "company/data/portfolios" / f"{advisor}.json"


def nav_path(root, advisor):
    return Path(root) / "company/data/nav" / f"{advisor}.json"


def load(root, advisor, opened=None):
    """The advisor's book, opened with the standard allocation if it is their first day."""
    book = _read(portfolio_path(root, advisor),
                 {"advisor": advisor, "cash": OPENING_CASH, "positions": {},
                  "opened": opened or dt.date.today().isoformat(),
                  "currency": "USD"})
    book.setdefault("advisor", advisor)
    book.setdefault("positions", {})
    book.setdefault("cash", OPENING_CASH)
    return book


def open_benchmark(root, prices, date):
    """Open the buy-and-hold book once, on the first day there are prices.

    Idempotent by existence: once the file is there this does nothing at all, so a
    re-run of the first day cannot re-buy it and a normal day cannot touch it.

    It buys only what could be priced that morning. An instrument the feed could
    not reach on day one is never bought later — buying it in week three at week
    three's price would make the benchmark a strategy, and a lucky one, since it
    would be entering things after seeing them. What it opened with is recorded in
    `opened_with` so the gap is visible rather than implied.
    """
    path = portfolio_path(root, BENCHMARK_ID)
    if path.exists():
        return _read(path, {})
    priced = {symbol: float(quote["close"])
              for symbol, quote in sorted(prices.items())
              if quote.get("close") and float(quote["close"]) > 0}
    if not priced:
        return None
    # Quantity is derived from the rounded cost rather than from the exact slice,
    # so that what the book paid and what the book holds agree to the cent on the
    # opening day. Derived the other way, the benchmark starts life a few cents
    # above $100,000 — which is nothing, except that it is not level with the
    # advisors, and being exactly level is the whole point of it.
    slice_usd = round(OPENING_CASH / len(priced), 2)
    positions = {symbol: {"qty": round(slice_usd / price, 8), "cost": slice_usd}
                 for symbol, price in priced.items()}
    spent = sum(p["cost"] for p in positions.values())
    book = {"advisor": BENCHMARK_ID, "cash": round(OPENING_CASH - spent, 2),
            "positions": positions, "opened": date, "currency": "USD",
            "frozen": True, "last_traded": date,
            "opened_with": sorted(priced)}
    _write(path, book)
    return book


def value(book, prices):
    """Mark a book to market. Returns (nav, invested, unpriced).

    An instrument with no price today is held at cost rather than dropped. A gap
    in a data feed is not a loss, and a NAV that quietly falls every time a
    provider hiccups would make the whole leaderboard a measure of the feed.
    """
    invested, unpriced = 0.0, []
    for symbol, held in book["positions"].items():
        quote = prices.get(symbol) or {}
        price = quote.get("close")
        if price and float(price) > 0:
            invested += held["qty"] * float(price)
        else:
            invested += held.get("cost", 0.0)
            unpriced.append(symbol)
    return round(book["cash"] + invested, 2), round(invested, 2), unpriced


def positions_view(book, prices):
    """Each holding with what it cost, what it is worth and what that is as a return."""
    rows = []
    for symbol, held in sorted(book["positions"].items()):
        price = (prices.get(symbol) or {}).get("close")
        worth = held["qty"] * float(price) if price and float(price) > 0 else held.get("cost", 0.0)
        cost = held.get("cost", 0.0)
        rows.append({"instrument": symbol, "qty": round(held["qty"], 6),
                     "cost": round(cost, 2), "value": round(worth, 2),
                     "priced": bool(price and float(price) > 0),
                     "return_pct": round((worth / cost - 1) * 100, 2) if cost else 0.0})
    return rows


def last_valued(root, advisor, before):
    """The last date this book was valued strictly before `before`, or None."""
    rows = _read(nav_path(root, advisor), {"series": []}).get("series") or []
    dates = sorted(r["date"] for r in rows if r.get("date") and r["date"] < before)
    return dates[-1] if dates else None


def price_book(root, date):
    """A recorded day's whole price book, or None."""
    if not date:
        return None
    return _read(Path(root) / "company/data/prices" / f"{date}.json", None)


def accrue(root, advisor, date, today_book):
    """Pay one book what it earned since it was last valued, once per date.

    Idempotent through `carried_to`: a shift re-run for the same day finds the
    book already carried and credits nothing, the way `mark()` writes a day once.
    Returns the carry record, or None when there was nothing to carry from.
    """
    since = last_valued(root, advisor, date)
    if not since:
        return None
    # A book that has been valued but never written — an advisor that has only
    # ever been unreachable — still holds its opening cash, and that cash earns.
    path = portfolio_path(root, advisor)
    book = load(root, advisor, opened=since)
    if str(book.get("carried_to", "")) >= str(date):
        return None
    record = carry(book, since, price_book(root, since), date, today_book)
    total = apply_carry(book, record)
    _write(path, book)
    record["credited"] = total
    return record


def mark(root, advisor, prices, date):
    """Value the book for `date` and record it in the NAV series. Idempotent."""
    book = load(root, advisor, opened=date)
    nav, invested, unpriced = value(book, prices)
    series = _read(nav_path(root, advisor), {"advisor": advisor, "series": []})
    series["advisor"] = advisor
    kept = [row for row in series.get("series", []) if row.get("date") != date]
    kept.append({"date": date, "nav": nav, "cash": round(book["cash"], 2),
                 "invested": invested, "unpriced": unpriced})
    series["series"] = sorted(kept, key=lambda r: r["date"])
    _write(nav_path(root, advisor), series)
    return nav, series


def execute(root, advisor, accepted, date):
    """Put a screened day's orders through the book and save it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "logic_risk", Path(root) / "company/agents/logic/risk.py")
    risk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(risk)

    book = load(root, advisor, opened=date)
    for order in accepted:
        risk.apply_order(book, order)
    book["cash"] = round(book["cash"], 2)
    for held in book["positions"].values():
        held["qty"] = round(held["qty"], 8)
        held["cost"] = round(held["cost"], 2)
    book["last_traded"] = date if accepted else book.get("last_traded", "")
    _write(portfolio_path(root, advisor), book)
    return book


def series_stats(series):
    """Return, drawdown and length, from a NAV series alone.

    Return is measured against the opening allocation rather than the first row,
    so an advisor who lost money on day one cannot improve its published record by
    having started badly.
    """
    rows = [r for r in series.get("series", []) if isinstance(r.get("nav"), (int, float))]
    if not rows:
        return {"nav": OPENING_CASH, "return_pct": 0.0, "max_drawdown_pct": 0.0,
                "days": 0, "best_day_pct": 0.0, "worst_day_pct": 0.0}
    navs = [float(r["nav"]) for r in rows]
    peak, drawdown = navs[0], 0.0
    for nav in navs:
        peak = max(peak, nav)
        if peak > 0:
            drawdown = max(drawdown, (peak - nav) / peak)
    steps = [(navs[i] / navs[i - 1] - 1) * 100 for i in range(1, len(navs)) if navs[i - 1]]
    return {"nav": round(navs[-1], 2),
            "return_pct": round((navs[-1] / OPENING_CASH - 1) * 100, 2),
            "max_drawdown_pct": round(drawdown * 100, 2),
            "days": len(navs),
            "best_day_pct": round(max(steps), 2) if steps else 0.0,
            "worst_day_pct": round(min(steps), 2) if steps else 0.0}


def window_return(series, since):
    """Return over the rows dated `since` or later — the month the evolution judges."""
    rows = sorted((r for r in series.get("series", []) if r.get("date")),
                  key=lambda r: r["date"])
    inside = [r for r in rows if r["date"] >= since]
    if len(inside) < 2:
        return None
    start = float(inside[0]["nav"])
    return round((float(inside[-1]["nav"]) / start - 1) * 100, 2) if start else None
