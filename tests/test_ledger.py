"""The book, and the two promises the public numbers rest on.

Valuation runs without a model, and a day is written once. Everything on the site
is read off these files, so if either promise breaks the site is wrong in a way no
reader could detect.
"""
PRICES = {"AAPL": {"close": 200.0}, "SPY": {"close": 500.0}}


def test_a_new_advisor_opens_with_the_standard_allocation(company, logic):
    ledger = logic(company, "ledger")
    book = ledger.load(company, "momentum", opened="2026-09-04")
    assert book["cash"] == ledger.OPENING_CASH and book["positions"] == {}
    assert ledger.value(book, PRICES)[0] == ledger.OPENING_CASH


def test_buying_moves_money_without_moving_the_net_asset_value(company, logic):
    ledger, risk = logic(company, "ledger"), logic(company, "risk")
    book = ledger.load(company, "value", opened="2026-09-04")
    ok, _ = risk.screen([{"action": "buy", "instrument": "AAPL", "amount_usd": 20_000}],
                        book, PRICES, {"AAPL"}, 100_000.0)
    after = ledger.execute(company, "value", ok, "2026-09-04")
    assert after["cash"] == 80_000.0
    assert after["positions"]["AAPL"]["qty"] == 100.0
    assert ledger.value(after, PRICES)[0] == 100_000.0


def test_valuation_needs_no_model_at_all(company, logic, monkeypatch):
    """The whole point: the page updates on a day every language model is down."""
    monkeypatch.setenv("MOCK_LLM", "")
    ledger = logic(company, "ledger")
    nav, series = ledger.mark(company, "careful", PRICES, "2026-09-04")
    assert nav == ledger.OPENING_CASH and len(series["series"]) == 1


def test_a_day_is_written_once_however_often_the_shift_is_rerun(company, logic):
    """Shifts here are re-run by hand, because a schedule has been seen to skip."""
    ledger = logic(company, "ledger")
    for _ in range(3):
        ledger.mark(company, "index", PRICES, "2026-09-04")
    series = ledger.mark(company, "index", PRICES, "2026-09-04")[1]
    assert [row["date"] for row in series["series"]] == ["2026-09-04"]


def test_a_rerun_carries_the_later_valuation(company, logic):
    ledger, risk = logic(company, "ledger"), logic(company, "risk")
    book = ledger.load(company, "macro", opened="2026-09-04")
    ok, _ = risk.screen([{"action": "buy", "instrument": "SPY", "amount_usd": 20_000}],
                        book, PRICES, {"SPY"}, 100_000.0)
    ledger.execute(company, "macro", ok, "2026-09-04")
    ledger.mark(company, "macro", PRICES, "2026-09-04")
    moved = {"SPY": {"close": 550.0}}
    nav, series = ledger.mark(company, "macro", moved, "2026-09-04")
    assert nav == 102_000.0 and len(series["series"]) == 1


def test_a_missing_price_is_a_gap_in_the_feed_not_a_loss(company, logic):
    """A NAV that fell every time a provider hiccuped would measure the provider."""
    ledger, risk = logic(company, "ledger"), logic(company, "risk")
    book = ledger.load(company, "metals", opened="2026-09-04")
    ok, _ = risk.screen([{"action": "buy", "instrument": "AAPL", "amount_usd": 20_000}],
                        book, PRICES, {"AAPL"}, 100_000.0)
    after = ledger.execute(company, "metals", ok, "2026-09-04")
    nav, invested, unpriced = ledger.value(after, {})
    assert nav == 100_000.0 and invested == 20_000.0 and unpriced == ["AAPL"]


def test_selling_part_of_a_holding_reduces_its_cost_in_proportion(company, logic):
    ledger, risk = logic(company, "ledger"), logic(company, "risk")
    book = ledger.load(company, "fx", opened="2026-09-04")
    ok, _ = risk.screen([{"action": "buy", "instrument": "AAPL", "amount_usd": 20_000}],
                        book, PRICES, {"AAPL"}, 100_000.0)
    ledger.execute(company, "fx", ok, "2026-09-04")
    held = ledger.load(company, "fx")
    ok, _ = risk.screen([{"action": "sell", "instrument": "AAPL", "amount_usd": 10_000}],
                        held, PRICES, {"AAPL"}, 100_000.0)
    after = ledger.execute(company, "fx", ok, "2026-09-05")
    assert round(after["positions"]["AAPL"]["cost"], 2) == 10_000.0
    assert round(after["positions"]["AAPL"]["qty"], 4) == 50.0


def test_selling_out_removes_the_position_rather_than_leaving_a_ghost(company, logic):
    ledger, risk = logic(company, "ledger"), logic(company, "risk")
    book = ledger.load(company, "contrarian", opened="2026-09-04")
    ok, _ = risk.screen([{"action": "buy", "instrument": "AAPL", "amount_usd": 20_000}],
                        book, PRICES, {"AAPL"}, 100_000.0)
    ledger.execute(company, "contrarian", ok, "2026-09-04")
    held = ledger.load(company, "contrarian")
    ok, _ = risk.screen([{"action": "sell", "instrument": "AAPL", "amount_usd": 999_999}],
                        held, PRICES, {"AAPL"}, 100_000.0)
    after = ledger.execute(company, "contrarian", ok, "2026-09-05")
    assert after["positions"] == {} and round(after["cash"], 2) == 100_000.0


def test_return_is_measured_from_the_opening_allocation(company, logic):
    """Not from the first row: a bad first day must not improve a published record."""
    ledger = logic(company, "ledger")
    series = {"series": [{"date": "2026-09-04", "nav": 90_000.0},
                         {"date": "2026-09-05", "nav": 99_000.0}]}
    stats = ledger.series_stats(series)
    assert stats["return_pct"] == -1.0


def test_drawdown_is_measured_from_the_peak(company, logic):
    ledger = logic(company, "ledger")
    series = {"series": [{"date": "2026-09-04", "nav": 100_000.0},
                         {"date": "2026-09-05", "nav": 120_000.0},
                         {"date": "2026-09-06", "nav": 90_000.0},
                         {"date": "2026-09-07", "nav": 110_000.0}]}
    stats = ledger.series_stats(series)
    assert stats["max_drawdown_pct"] == 25.0
    assert stats["worst_day_pct"] == -25.0


def test_an_empty_series_does_not_crash_the_standings(company, logic):
    ledger = logic(company, "ledger")
    assert ledger.series_stats({"series": []})["days"] == 0
    assert ledger.window_return({"series": []}, "2026-01-01") is None


# --------------------------------------------------------------------------
# The thing the advisors are actually competing with.
# --------------------------------------------------------------------------

def _quotes(**prices):
    return {symbol: {"close": price} for symbol, price in prices.items()}


def test_buy_and_hold_opens_with_the_whole_book_in_equal_weight(company, logic):
    ledger = logic(company, "ledger")
    book = ledger.open_benchmark(company, _quotes(A=100.0, B=50.0, C=25.0),
                                 "2026-09-04")
    assert set(book["positions"]) == {"A", "B", "C"}
    for position in book["positions"].values():
        assert position["cost"] == round(ledger.OPENING_CASH / 3, 2)
    assert book["positions"]["B"]["qty"] == round(
        book["positions"]["B"]["cost"] / 50.0, 8)
    nav, _, _ = ledger.value(book, _quotes(A=100.0, B=50.0, C=25.0))
    assert nav == ledger.OPENING_CASH, "it starts level with every advisor, to the cent"


def test_buy_and_hold_is_opened_once_and_never_again(company, logic):
    """A re-run of the first day must not re-buy it, and no later day may touch it."""
    ledger = logic(company, "ledger")
    first = ledger.open_benchmark(company, _quotes(A=100.0, B=50.0), "2026-09-04")
    again = ledger.open_benchmark(company, _quotes(A=200.0, B=25.0), "2026-09-05")
    assert again["positions"] == first["positions"]
    assert again["opened"] == "2026-09-04"


def test_buy_and_hold_never_buys_what_the_feed_missed_on_day_one(company, logic):
    """Entering an instrument in week three, at week three's price, is hindsight.

    It would also quietly turn the benchmark into a strategy — and a good one,
    since it would only ever open positions in things that had started printing.
    """
    ledger = logic(company, "ledger")
    book = ledger.open_benchmark(company, _quotes(A=100.0, B=50.0), "2026-09-04")
    assert book["opened_with"] == ["A", "B"]
    later = ledger.open_benchmark(company, _quotes(A=100.0, B=50.0, C=10.0),
                                  "2026-09-20")
    assert "C" not in later["positions"]


def test_with_no_price_at_all_there_is_nothing_to_open(company, logic):
    ledger = logic(company, "ledger")
    assert ledger.open_benchmark(company, {}, "2026-09-04") is None
    assert not ledger.portfolio_path(company, ledger.BENCHMARK_ID).exists()
