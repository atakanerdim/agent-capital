"""The limits, and the reason they are not in a prompt.

Everything else about an advisor is soft — a brief that another agent rewrites once
a month on the evidence of a bad month. If a position limit lived in that brief,
one month of feedback could produce an advisor with no limit and a fence that had
been edited by the thing it was fencing.

So the limits live in code no agent may touch, on the only path from an opinion to
the book, and CI refuses a pull request that changes the file. These tests hold
the numbers to that file.
"""
import pytest

PRICES = {"AAPL": {"close": 200.0}, "SPY": {"close": 500.0},
          "XAUUSD": {"close": 2000.0}, "MUTE": {"close": 0}}
UNIVERSE = {"AAPL", "SPY", "XAUUSD", "MUTE"}


def book(cash=100_000.0, **positions):
    return {"advisor": "t", "cash": cash,
            "positions": {k: {"qty": v[0], "cost": v[1]} for k, v in positions.items()}}


def test_an_ordinary_order_reaches_the_book(logic):
    risk = logic(".", "risk")
    ok, no = risk.screen([{"action": "buy", "instrument": "AAPL",
                           "amount_usd": 5000, "reason": "trend"}],
                         book(), PRICES, UNIVERSE, 100_000.0)
    assert not no
    assert ok[0]["qty"] == 25.0 and ok[0]["amount_usd"] == 5000.0


def test_the_desk_never_borrows(logic):
    risk = logic(".", "risk")
    ok, no = risk.screen([{"action": "buy", "instrument": "AAPL", "amount_usd": 120_000}],
                         book(), PRICES, UNIVERSE, 100_000.0)
    assert not ok and "does not borrow" in no[0]["why"]


def test_orders_are_screened_against_the_book_they_will_leave_behind(logic):
    """Five orders for a quarter each are not five orders for a quarter each.

    Screened against the opening book every time, each of these looks like exactly
    the limit and all five pass; the advisor ends the morning fully invested with
    no cash while every rule reports that it held.
    """
    risk = logic(".", "risk")
    orders = [{"action": "buy", "instrument": i, "amount_usd": 25_000}
              for i in ("AAPL", "SPY", "XAUUSD")] * 2
    ok, no = risk.screen(orders, book(), PRICES, UNIVERSE, 100_000.0)
    assert sum(o["amount_usd"] for o in ok) <= 100_000.0
    assert no, "the order that ran out of money must be refused"


def test_no_instrument_may_pass_a_quarter_of_the_book(logic):
    risk = logic(".", "risk")
    ok, no = risk.screen([{"action": "buy", "instrument": "AAPL", "amount_usd": 40_000}],
                         book(), PRICES, UNIVERSE, 100_000.0)
    assert not ok and "25%" in no[0]["why"]


def test_a_position_already_held_counts_towards_the_limit(logic):
    risk = logic(".", "risk")
    ok, no = risk.screen([{"action": "buy", "instrument": "AAPL", "amount_usd": 15_000}],
                         book(cash=85_000.0, AAPL=(75.0, 15_000.0)), PRICES,
                         UNIVERSE, 100_000.0)
    assert not ok and "25%" in no[0]["why"]


def test_nothing_off_the_list_is_tradable(logic):
    risk = logic(".", "risk")
    ok, no = risk.screen([{"action": "buy", "instrument": "DOGE", "amount_usd": 5000}],
                         book(), PRICES, UNIVERSE, 100_000.0)
    assert not ok and "not on the desk's instrument list" in no[0]["why"]


def test_an_instrument_with_no_price_today_cannot_be_traded(logic):
    risk = logic(".", "risk")
    ok, no = risk.screen([{"action": "buy", "instrument": "MUTE", "amount_usd": 5000}],
                         book(), PRICES, UNIVERSE, 100_000.0)
    assert not ok and "no price" in no[0]["why"]


def test_the_desk_does_not_sell_what_it_does_not_own(logic):
    risk = logic(".", "risk")
    ok, no = risk.screen([{"action": "sell", "instrument": "SPY", "amount_usd": 1000}],
                         book(), PRICES, UNIVERSE, 100_000.0)
    assert not ok and "do not hold" in no[0]["why"]


def test_selling_more_than_you_hold_sells_all_of_it(logic):
    """A normal thing to mean, and not worth refusing an advisor over."""
    risk = logic(".", "risk")
    ok, no = risk.screen([{"action": "sell", "instrument": "AAPL", "amount_usd": 999_999}],
                         book(cash=0.0, AAPL=(10.0, 1800.0)), PRICES, UNIVERSE, 2000.0)
    assert not no and ok[0]["amount_usd"] == 2000.0


def test_dust_is_not_a_position(logic):
    risk = logic(".", "risk")
    ok, no = risk.screen([{"action": "buy", "instrument": "AAPL", "amount_usd": 10}],
                         book(), PRICES, UNIVERSE, 100_000.0)
    assert not ok and "minimum" in no[0]["why"]


def test_an_advisor_is_not_a_day_trading_bot(logic):
    risk = logic(".", "risk")
    orders = [{"action": "buy", "instrument": "AAPL", "amount_usd": 1000}] * 8
    ok, no = risk.screen(orders, book(), PRICES, UNIVERSE, 100_000.0)
    assert len(ok) == risk.MAX_ORDERS_PER_DAY
    assert any("limit" in r["why"] for r in no)


def test_nonsense_is_refused_rather_than_crashing_the_shift(logic):
    risk = logic(".", "risk")
    ok, no = risk.screen(
        [None, "buy everything", {"action": "levitate", "instrument": "AAPL"},
         {"action": "buy", "instrument": "AAPL", "amount_usd": "a lot"},
         {"action": "buy", "instrument": "AAPL", "amount_usd": float("nan")}],
        book(), PRICES, UNIVERSE, 100_000.0)
    assert not ok and len(no) == 5


def test_the_portfolio_passed_in_is_never_modified(logic):
    risk = logic(".", "risk")
    original = book()
    before = repr(original)
    risk.screen([{"action": "buy", "instrument": "AAPL", "amount_usd": 5000}],
                original, PRICES, UNIVERSE, 100_000.0)
    assert repr(original) == before
