"""Run a policy over the days that actually happened.

The desk records the whole price book every morning, not only the instruments it
traded. That one habit is what separates a log from an environment: because every
price the desk could have traded at is on disk, the question "what would this
other policy have done" has an arithmetic answer rather than a simulated one.
Nothing here fetches, and nothing here models — it walks the recorded days in
order and puts a policy's orders through the same ledger the advisors use.

Two things this module is careful about.

**It uses the same arithmetic as the real desk.** `risk.screen` and
`risk.apply_order` are imported from the same files the shift runs, not
reimplemented. A replay that valued books its own way would drift from the desk
by a little every month and be worth nothing exactly when it started to matter.

**A policy sees one day at a time and never the future.** `run()` hands the policy
the date, that day's quotes and its current book, and nothing else. There is no
argument through which tomorrow can arrive, which is the only reliable defence
against look-ahead: not discipline, but an interface that cannot express it.

The invariant that makes the archive trustworthy is tested rather than asserted:
replaying the orders the desk actually recorded, over the prices it actually
recorded, must reproduce the NAV series it actually published, to the cent. While
that test is green the archive is a faithful environment. The day it goes red,
the record and the reality have come apart, and it says so immediately instead of
three months later.
"""
import copy
import importlib.util
import json
from pathlib import Path


def _logic(root, name):
    spec = importlib.util.spec_from_file_location(
        f"logic_{name}", Path(root) / "company/agents/logic" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_series(root):
    """Every recorded trading day, oldest first: [(date, quotes), ...].

    A day whose file will not parse is skipped rather than guessed at, and the
    skip is visible in the length of what comes back.
    """
    folder = Path(root) / "company/data/prices"
    days = []
    for path in sorted(folder.glob("*.json")):
        try:
            book = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        quotes = book.get("quotes")
        if quotes:
            days.append((book.get("date") or path.stem, quotes))
    return days


def load_orders(root):
    """What each advisor was recorded as having done, by date: {date: {advisor: [...]}}."""
    folder = Path(root) / "company/data/orders"
    out = {}
    for path in sorted(folder.glob("*.json")):
        try:
            day = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out[day.get("date") or path.stem] = {
            advisor: record.get("orders") or []
            for advisor, record in (day.get("advisors") or {}).items()}
    return out


def empty_book(opening_cash, opened):
    return {"advisor": "replay", "cash": float(opening_cash), "positions": {},
            "opened": opened, "currency": "USD"}


def run(root, policy, series=None, opening_cash=None, screen=True):
    """Walk the recorded days, one policy, one book. Returns (book, nav_series).

    `policy(date, quotes, book) -> orders` is called once per day with a *copy* of
    the book, so a policy cannot reach into the ledger and move its own money.

    `screen=True` puts the policy's orders through the desk's real risk rules —
    the same limits the advisors live under, which is what makes a comparison
    against them mean anything. Set it False only to replay orders that were
    already screened when they were made; screening a second time would refuse
    orders the desk accepted, on a book the second screening is rebuilding.
    """
    ledger = _logic(root, "ledger")
    risk = _logic(root, "risk")
    market = _logic(root, "market")
    universe = {i["id"] for i in market.load_universe(root)}

    days = series if series is not None else load_series(root)
    cash = ledger.OPENING_CASH if opening_cash is None else opening_cash
    book = empty_book(cash, days[0][0] if days else "")
    navs = []
    for date, quotes in days:
        nav, _, _ = ledger.value(book, quotes)
        orders = policy(date, quotes, copy.deepcopy(book)) or []
        if screen:
            orders, _ = risk.screen(orders, book, quotes, universe, nav)
        for order in orders:
            risk.apply_order(book, order)
        book["cash"] = round(book["cash"], 2)
        for held in book["positions"].values():
            held["qty"] = round(held["qty"], 8)
            held["cost"] = round(held["cost"], 2)
        nav, invested, unpriced = ledger.value(book, quotes)
        navs.append({"date": date, "nav": nav, "cash": round(book["cash"], 2),
                     "invested": invested, "unpriced": unpriced})
    return book, navs


def replay_advisor(root, advisor, series=None, orders_by_date=None):
    """Re-run one advisor's own recorded orders. The archive's self-check.

    Orders are replayed unscreened because they were screened when they were made:
    what is on disk is what reached the book. Screening them again would judge each
    one against a book being rebuilt, and refuse things the desk accepted.
    """
    days = series if series is not None else load_series(root)
    recorded = load_orders(root) if orders_by_date is None else orders_by_date

    def policy(date, quotes, book):
        return (recorded.get(date) or {}).get(advisor) or []

    return run(root, policy, series=days, screen=False)


# --------------------------------------------------------------------------
# What every other choice would have done.
#
# The desk sees the outcome of the order it sent and nothing else. That is bandit
# feedback, and it is the expensive kind: a year of it teaches about as much as a
# handful of days of the alternative. But the price book for every instrument the
# desk could have traded is already on disk, so the outcome of every order it did
# *not* send is not a simulation — it is a subtraction. Recovering it turns the
# archive from bandit feedback into full information, which is worth roughly a
# factor of three in effective sample size across a universe this size, for the
# cost of some arithmetic and no new data at all.
#
# The reason this is legitimate here and would not be at a real fund: these trades
# do not move prices. "What would gold have done" is answerable only when buying
# the gold would not have changed the gold price. Paper trading is a toy, and this
# is the one place the toy is strictly better than the real thing.
#
# What it does not fix: the twenty-seven outcomes on a given day share that day's
# shock. More rows, not more independent days.
# --------------------------------------------------------------------------

def _forward_date(dates, start, calendar_days):
    """The first recorded day on or after `start` + `calendar_days`, or None.

    An advisor states a horizon in calendar days because that is how people think,
    but the archive only holds the days the desk actually ran. This maps one to the
    other by looking forward, never by interpolating a price for a day that has no
    record — and returns None rather than the last available day when the horizon
    runs past the end of the archive. A horizon that has not finished yet is not a
    result of zero; scoring it as one would make every recent decision look flat.
    """
    import datetime as _dt
    try:
        target = (_dt.date.fromisoformat(start)
                  + _dt.timedelta(days=int(calendar_days))).isoformat()
    except (ValueError, TypeError):
        return None
    return next((d for d in dates if d >= target), None)


def counterfactual_grid(root, series=None, horizons=(1, 5, 20)):
    """For every recorded day and instrument: what holding it would have returned.

    Returns {date: {horizon: {instrument: return_fraction}}}. An instrument without
    a price on either end is absent rather than zero, and a horizon that runs off
    the end of the archive is absent too.
    """
    days = series if series is not None else load_series(root)
    by_date = {date: quotes for date, quotes in days}
    dates = sorted(by_date)
    grid = {}
    for date in dates:
        here = {}
        for horizon in horizons:
            later = _forward_date(dates, date, horizon)
            if later is None or later == date:
                continue
            outcome = {}
            for symbol, quote in by_date[date].items():
                start = quote.get("close")
                end = (by_date[later].get(symbol) or {}).get("close")
                if start and end and float(start) > 0:
                    outcome[symbol] = round(float(end) / float(start) - 1, 8)
            if outcome:
                here[horizon] = outcome
        if here:
            grid[date] = here
    return grid


def score_decision(root, date, order, series=None):
    """One order against the alternatives it was chosen over, on its own horizon.

    Returns the chosen instrument's realised return, each alternative's, and the
    rank of the choice among them — which is the shape a preference model wants and
    the shape the archive can produce for free.

    The horizon is the advisor's own stated one. Judging a thesis on a window it
    never claimed is how a slow idea gets recorded as a bad one; where no horizon
    was stated the decision is simply not scorable, and says so.
    """
    days = series if series is not None else load_series(root)
    by_date = {d: q for d, q in days}
    dates = sorted(by_date)
    horizon = order.get("horizon_days")
    if not horizon:
        return {"scorable": False, "why": "the advisor stated no horizon"}
    later = _forward_date(dates, date, horizon)
    if later is None:
        return {"scorable": False,
                "why": f"the archive does not reach {horizon} days past {date}"}

    def move(symbol):
        start = (by_date[date].get(symbol) or {}).get("close")
        end = (by_date[later].get(symbol) or {}).get("close")
        if start and end and float(start) > 0:
            return round(float(end) / float(start) - 1, 8)
        return None

    chosen = str(order.get("instrument", "")).upper()
    taken = move(chosen)
    alternatives = [{"instrument": item["instrument"],
                     "why_not": item.get("why_not", ""),
                     "return": move(item["instrument"])}
                    for item in order.get("considered") or []]
    scored = [a for a in alternatives if a["return"] is not None]
    beaten = sum(1 for a in scored if taken is not None and taken > a["return"])
    return {"scorable": taken is not None, "date": date, "asof": later,
            "horizon_days": horizon, "instrument": chosen, "return": taken,
            "conviction": order.get("conviction"),
            "alternatives": alternatives,
            "beat": beaten, "of": len(scored)}


def score_all(root, series=None):
    """Every recorded order scored against its own alternatives. The preference set."""
    days = series if series is not None else load_series(root)
    out = []
    for date, orders in sorted(load_orders(root).items()):
        for advisor, records in orders.items():
            for order in records:
                result = score_decision(root, date, order, series=days)
                if result.get("scorable"):
                    out.append(dict(result, advisor=advisor))
    return out


def buy_and_hold(root, series=None, opening_cash=None):
    """Equal weight into everything priced on the first day, then nothing.

    The same rule the desk's own benchmark book follows, expressed as a policy so
    that it can be replayed over any window rather than only from the desk's
    opening day.
    """
    ledger = _logic(root, "ledger")
    days = series if series is not None else load_series(root)
    cash = ledger.OPENING_CASH if opening_cash is None else opening_cash
    opened = days[0][0] if days else None

    def policy(date, quotes, book):
        if date != opened:
            return []
        priced = sorted((s, float(q["close"])) for s, q in quotes.items()
                        if q.get("close") and float(q["close"]) > 0)
        if not priced:
            return []
        slice_usd = round(cash / len(priced), 2)
        # Orders go in already screened, so they arrive in the shape risk hands to
        # the book: quantity and price settled, not an amount to be worked out.
        return [{"action": "buy", "instrument": symbol,
                 "qty": round(slice_usd / price, 8), "price": price,
                 "amount_usd": slice_usd, "reason": "equal weight, opening day",
                 "conviction": None, "horizon_days": None}
                for symbol, price in priced]

    return run(root, policy, series=days, opening_cash=cash, screen=False)
