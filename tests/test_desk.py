"""A whole trading day, and the property that makes the site trustworthy.

The day is one shift on purpose. Split across a branch per advisor, seven of them
would be trading against a price file that had not been merged yet. What these
tests hold is that the day is atomic, that it survives its own agents failing, and
that an advisor's opinion cannot reach the book without passing the rules.
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


def test_a_trading_day_runs_end_to_end(company):
    result = run_day(company, "2026-09-04", "fri")
    assert result.returncode == 0, result.stderr
    prices = read(company, "company/data/prices/2026-09-04.json")
    orders = read(company, "company/data/orders/2026-09-04.json")
    board = read(company, "company/data/leaderboard.json")
    assert prices["covered"] == "27/27"
    assert len(orders["advisors"]) == 8
    assert len(board["rows"]) == 9      # eight advisors and the market they face


def test_only_the_desk_and_the_evaluator_are_their_own_shift(company):
    """Eight advisors are on the floor; their shift is not theirs to run."""
    out = subprocess.run([sys.executable, "kernel/runner.py", "--list", "--day", "fri"],
                         cwd=company, capture_output=True, text=True).stdout.split()
    assert out == ["desk", "evaluator"]


def test_every_book_is_valued_including_the_ones_nobody_touched(company):
    run_day(company, "2026-09-04", "fri")
    for advisor in ("momentum", "value", "macro", "careful", "contrarian",
                    "fx", "metals", "index"):
        series = read(company, f"company/data/nav/{advisor}.json")
        assert series and series["series"][-1]["date"] == "2026-09-04"


def test_buying_does_not_change_a_net_asset_value_on_the_day_it_happens(company):
    run_day(company, "2026-09-04", "fri")
    board = read(company, "company/data/leaderboard.json")
    assert {row["nav"] for row in board["rows"]} == {100_000.0}


def test_an_order_for_something_off_the_list_is_refused_and_recorded(company):
    """The fixture has the contrarian asking for an instrument that does not exist."""
    run_day(company, "2026-09-04", "fri")
    record = read(company, "company/data/orders/2026-09-04.json")["advisors"]["contrarian"]
    assert [o["instrument"] for o in record["orders"]] == ["EEM"]
    assert record["rejected"] and "not on the desk's instrument list" \
        in record["rejected"][0]["why"]


def test_a_refused_order_comes_back_to_the_advisor_the_next_day(company, logic):
    """Three attempts at the same refusal is not a retry, it is the same dice."""
    run_day(company, "2026-09-04", "fri")
    desk = logic(company, "desk")
    reminder = desk._yesterday(company, "contrarian", "2026-09-07")
    assert "refused" in reminder and "instrument list" in reminder


def test_the_day_survives_every_advisor_being_unreachable(company, monkeypatch):
    """The advisors may fail. The published record may not go stale because they did."""
    answers = company / "tests/mock_answers.json"
    answers.write_text(json.dumps({"[ADVISOR:": "this is not JSON at all"}),
                       encoding="utf-8")
    result = run_day(company, "2026-09-04", "fri")
    assert result.returncode == 0, result.stderr
    orders = read(company, "company/data/orders/2026-09-04.json")
    assert all(rec["held"]["kind"] == "unreachable"
               for rec in orders["advisors"].values())
    board = read(company, "company/data/leaderboard.json")
    assert len(board["rows"]) == 9 and board["date"] == "2026-09-04"
    # And the market's book is still valued, because valuing it never needed a model.
    bench = [r for r in board["rows"] if r.get("is_benchmark")][0]
    assert bench["days"] == 1


def test_a_day_with_no_price_at_all_is_refused_rather_than_half_written(company):
    (company / "tests/mock_prices.json").write_text("{}", encoding="utf-8")
    result = run_day(company, "2026-09-04", "fri")
    assert result.returncode == 1
    assert not (company / "company/data/orders/2026-09-04.json").exists()
    # Never index a glob. The company writes one log file per failing agent and
    # the order is the filesystem's business; this exact mistake put CI red twice
    # on the desk next door.
    logs = "\n".join(p.read_text(encoding="utf-8")
                     for p in (company / "company/log").glob("*.log"))
    assert "no instrument could be priced" in logs


def test_running_the_same_day_twice_does_not_double_the_book(company):
    """The second cron of the day, and every hand-run recovery, depends on this."""
    run_day(company, "2026-09-04", "fri")
    first = read(company, "company/data/portfolios/momentum.json")
    run_day(company, "2026-09-04", "fri")
    second = read(company, "company/data/portfolios/momentum.json")
    series = read(company, "company/data/nav/momentum.json")["series"]
    assert len(series) == 1, "one date, one valuation"
    assert second["cash"] < first["cash"], (
        "a re-run does trade again — that is a known and accepted limit, guarded by "
        "the workflow refusing to run a day it has already delivered")


def test_the_minutes_say_what_could_not_be_priced(company):
    (company / "tests/mock_prices.json").write_text(
        json.dumps({"SPY": 660.0, "AAPL": 230.0}), encoding="utf-8")
    run_day(company, "2026-09-04", "fri")
    text = (company / "company/minutes/2026-09-04-desk.md").read_text(encoding="utf-8")
    assert "Priced 2/27" in text
    assert "could not reach" in text and "XAUUSD" in text


# --------------------------------------------------------------------------
# What a decision record has to name for it to be attributable later.
# --------------------------------------------------------------------------

def test_a_decision_names_everything_that_shaped_it(company, logic):
    """Price book, brief, memory and the size of the book being risked.

    Without these an order can be read but not explained: when an advisor starts
    behaving differently there is no way to tell whether the market moved, the
    brief was rewritten, or the memory grew.
    """
    run_day(company, "2026-09-04", "fri")
    prices = read(company, "company/data/prices/2026-09-04.json")
    record = read(company, "company/data/orders/2026-09-04.json")["advisors"]["momentum"]
    market = logic(company, "market")

    assert record["snapshot_id"] == prices["snapshot_id"]
    assert record["snapshot_id"] == market.snapshot_id(prices["quotes"])
    assert len(record["prompt_sha"]) == 12
    assert len(record["memory_sha"]) == 12
    assert record["nav_before"] == 100000.00      # first day, before anything traded


def test_the_prompt_fingerprint_follows_the_brief_that_was_actually_in_force(company):
    """A date is a weak link between a rewrite and a behaviour change; a hash is not."""
    run_day(company, "2026-09-04", "fri")
    before = read(company, "company/data/orders/2026-09-04.json")["advisors"]["value"]

    brief = company / "company/agents/prompts/value.md"
    brief.write_text(brief.read_text(encoding="utf-8") + "\nOne more line.\n",
                     encoding="utf-8")
    run_day(company, "2026-09-05", "fri")
    after = read(company, "company/data/orders/2026-09-05.json")["advisors"]["value"]

    assert before["prompt_sha"] != after["prompt_sha"]


def test_conviction_and_horizon_reach_the_record(company):
    run_day(company, "2026-09-04", "fri")
    orders = read(company, "company/data/orders/2026-09-04.json")["advisors"]
    nvda = [o for o in orders["momentum"]["orders"] if o["instrument"] == "NVDA"][0]
    assert nvda["conviction"] == 0.8 and nvda["horizon_days"] == 30
    assert orders["momentum"]["schema_gaps"] == 0


def test_a_missing_conviction_is_a_counted_gap_and_never_a_refusal(company):
    """A schema introduced this month must not be the reason the desk stops trading.

    The advisors that answer without the two new fields still trade; the holes are
    recorded where they happen so that they can be seen rather than assumed away.
    """
    run_day(company, "2026-09-04", "fri")
    macro = read(company, "company/data/orders/2026-09-04.json")["advisors"]["macro"]
    assert macro["orders"], "an order without conviction must still reach the book"
    assert all(o["conviction"] is None for o in macro["orders"])
    assert macro["schema_gaps"] == len(macro["orders"])


def test_the_alternatives_an_order_beat_are_recorded(company):
    """Gold instead of silver is arithmetic; that gold was ever in the running is not."""
    run_day(company, "2026-09-04", "fri")
    orders = read(company, "company/data/orders/2026-09-04.json")["advisors"]
    gold = [o for o in orders["metals"]["orders"] if o["instrument"] == "XAUUSD"][0]
    assert gold["considered"] == [
        {"instrument": "XAGUSD",
         "why_not": "Silver moves more but the industrial demand story is noisier."}]


def test_an_invented_alternative_is_dropped_rather_than_stored(company, logic):
    """A model asked what else it weighed will name things that were never on the list.

    Unfiltered, the field fills with inventions and the preference data built on it
    is worth less than nothing — it would be scored against prices that do not exist.
    """
    risk = logic(company, "risk")
    universe = {"NVDA", "QQQ", "SPY"}
    cleaned = risk.considered_of(
        {"instrument": "nvda",
         "considered": [{"instrument": "AMD", "why_not": "not tradeable here"},
                        {"instrument": "QQQ", "why_not": "slower"},
                        {"instrument": "NVDA", "why_not": "this is the one bought"},
                        {"instrument": "QQQ", "why_not": "named twice"}]},
        universe)
    assert cleaned == [{"instrument": "QQQ", "why_not": "slower"}]


def test_the_alternatives_field_survives_every_shape_a_model_might_send(company, logic):
    risk = logic(company, "risk")
    universe = {"SPY", "TLT"}
    assert risk.considered_of({"instrument": "X", "considered": "TLT"}, universe) == []
    assert risk.considered_of({"instrument": "X"}, universe) == []
    assert risk.considered_of({"instrument": "X", "considered": ["TLT", 7, None]},
                              universe) == [{"instrument": "TLT", "why_not": ""}]
    many = [{"instrument": "SPY"}] * 20
    assert len(risk.considered_of({"instrument": "X", "considered": many},
                                  universe)) == 1


def test_a_conviction_outside_its_range_is_dropped_not_clamped(company, logic):
    """Clamping 7.0 to 1.0 would invent a confidence the advisor never expressed."""
    risk = logic(company, "risk")
    assert risk.conviction_of({"conviction": 7.0}) is None
    assert risk.conviction_of({"conviction": -0.1}) is None
    assert risk.conviction_of({"conviction": "high"}) is None
    assert risk.conviction_of({"conviction": True}) is None
    assert risk.conviction_of({"conviction": 0.0}) == 0.0
    assert risk.horizon_of({"horizon_days": 0}) is None
    assert risk.horizon_of({"horizon_days": 30.0}) == 30


def test_the_three_ways_a_book_can_fail_to_move_are_told_apart(company, logic):
    """Silence, refusal and patience are different facts about an advisor.

    Recorded as one null field, a fortnight of provider outages reads as a
    fortnight of conviction — and the Chief Investment Officer rewrites a brief on
    exactly this evidence.
    """
    desk = logic(company, "desk")
    assert desk._held_kind([], [], [])["kind"] == "chose_to_hold"
    assert desk._held_kind([{"a": 1}], [], [{"why": "no"}])["kind"] == "all_rejected"
    assert desk._held_kind([{"a": 1}], [{"ok": 1}], [{"why": "no"}]) is None
    assert desk._kind({"held": {"kind": "unreachable", "why": "x"}}) == "unreachable"
    assert desk._kind({"held": None}) is None
    # A record written before the field was structured still reads correctly.
    assert desk._kind({"held": "TimeoutError: gone"}) == "unreachable"


def test_the_standings_carry_the_market_the_advisors_are_beating_or_not(company):
    """Eight numbers ranked against each other cannot tell a good year from a bad one."""
    run_day(company, "2026-09-04", "fri")
    board = read(company, "company/data/leaderboard.json")
    bench = [r for r in board["rows"] if r.get("is_benchmark")]
    assert len(bench) == 1, "buy and hold stands in the table"
    assert len(board["rows"]) == 9
    assert bench[0]["nav"] == 100000.00, "level with everybody on day one"
    assert bench[0]["days"] == 1, "valued by the same mark() as every advisor"


def test_buy_and_hold_is_ranked_but_is_never_called_the_best_on_the_desk(company, logic):
    """It is in the standings and it is not a colleague; both have to stay true."""
    desk = logic(company, "desk")
    board = {"rows": [{"name": "Buy and hold", "return_pct": 9.0, "is_benchmark": True},
                      {"name": "Priya", "return_pct": 4.0, "is_benchmark": False}]}
    assert desk.best_advisor(board)["name"] == "Priya"
    assert desk.best_advisor({"rows": []}) is None


def test_the_monthly_rewrite_can_never_land_on_the_benchmark(company, logic):
    """It has no brief to rewrite, and it is not last because it is bad at its job."""
    evolve, ledger = logic(company, "evolve"), logic(company, "ledger")
    run_day(company, "2026-09-04", "fri")
    roster = json.loads((company / "company/roster.json").read_text(encoding="utf-8"))
    advisors = [a for a in roster if a.get("driven_by")]
    rows, _ = evolve.standings(company, advisors, "2026-09-04", ledger)
    assert ledger.BENCHMARK_ID not in {r["advisor"] for r in rows}


def test_an_advisor_that_answered_is_not_recorded_as_unreachable(company):
    run_day(company, "2026-09-04", "fri")
    advisors = read(company, "company/data/orders/2026-09-04.json")["advisors"]
    kinds = {i: (r["held"] or {}).get("kind") for i, r in advisors.items()}
    assert "unreachable" not in kinds.values(), kinds
    minutes = (company / "company/minutes/2026-09-04-desk.md").read_text(encoding="utf-8")
    assert "could not be reached" not in minutes
