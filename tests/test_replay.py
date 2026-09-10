"""The archive has to be replayable, or it is only a diary.

The desk saves the whole price book every morning, not just what it traded. That
makes "what would this other policy have done" an arithmetic question instead of a
simulated one — but only while the record and the reality agree. These tests hold
that they do.

The first one is the important one, and it is worth saying plainly what it buys:
if replaying the desk's own recorded orders over the desk's own recorded prices
reproduces the desk's own published NAV series to the cent, then the archive is a
faithful environment and anything trained or measured on it is measuring the
company that actually ran. If that test ever goes red, something has been written
to disk that did not happen, and everything downstream of the archive is suspect —
which is a thing to learn the same day rather than three months later.
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


def three_days(company):
    """Three recorded trading days, with prices that actually move between them."""
    prices = json.loads((company / "tests/mock_prices.json").read_text(encoding="utf-8"))
    run_day(company, "2026-09-04", "fri")
    (company / "tests/mock_prices.json").write_text(
        json.dumps({k: round(v * 1.02, 6) for k, v in prices.items()}), encoding="utf-8")
    run_day(company, "2026-09-07", "mon")
    (company / "tests/mock_prices.json").write_text(
        json.dumps({k: round(v * 0.97, 6) for k, v in prices.items()}), encoding="utf-8")
    run_day(company, "2026-09-08", "tue")


def test_replaying_the_record_reproduces_the_published_nav_to_the_cent(company, logic):
    """The invariant the whole archive rests on.

    Every advisor, every recorded day: put the orders that are on disk through the
    prices that are on disk, and the NAV series that comes out has to be the NAV
    series that was published. Anything else means the site is showing a number
    the record cannot account for.
    """
    replay = logic(company, "replay")
    three_days(company)
    roster = json.loads((company / "company/roster.json").read_text(encoding="utf-8"))

    checked = 0
    for advisor in [a for a in roster if a.get("driven_by")]:
        published = read(company, f"company/data/nav/{advisor['id']}.json")["series"]
        _, replayed = replay.replay_advisor(company, advisor["id"])
        assert len(replayed) == len(published), advisor["id"]
        for was, now in zip(published, replayed):
            assert was["date"] == now["date"]
            assert was["nav"] == now["nav"], (
                f"{advisor['id']} on {was['date']}: published {was['nav']}, "
                f"the record replays to {now['nav']}")
            assert was["cash"] == now["cash"]
        checked += 1
    assert checked == 8


def test_the_benchmark_book_replays_to_its_own_published_series(company, logic):
    """The benchmark is opened by the desk and replayed by a policy written here.

    Two separate pieces of code arriving at the same series is the point: it means
    buy-and-hold can be re-measured over any window later without trusting that a
    file on disk was written correctly the first time.
    """
    replay, ledger = logic(company, "replay"), logic(company, "ledger")
    three_days(company)
    published = read(company, f"company/data/nav/{ledger.BENCHMARK_ID}.json")["series"]
    _, replayed = replay.buy_and_hold(company)
    assert [r["date"] for r in replayed] == [r["date"] for r in published]
    for was, now in zip(published, replayed):
        assert abs(was["nav"] - now["nav"]) < 0.01, was["date"]


def test_a_policy_is_handed_one_day_and_no_way_to_reach_the_next(company, logic):
    """Look-ahead is prevented by the interface, not by remembering not to do it."""
    replay = logic(company, "replay")
    three_days(company)
    seen = []

    def policy(date, quotes, book):
        seen.append((date, sorted(quotes)[:1]))
        return []

    replay.run(company, policy)
    dates = [d for d, _ in seen]
    assert dates == sorted(dates) and len(dates) == 3
    # The only arguments are today's date, today's quotes and today's book. There
    # is no parameter through which a later day could arrive.
    assert policy.__code__.co_varnames[:3] == ("date", "quotes", "book")


def test_a_policy_cannot_move_money_by_editing_the_book_it_is_shown(company, logic):
    replay = logic(company, "replay")
    three_days(company)

    def greedy(date, quotes, book):
        book["cash"] = 10_000_000.0
        book["positions"]["SPY"] = {"qty": 1000.0, "cost": 1.0}
        return []

    book, navs = replay.run(company, greedy)
    # Idle cash earns the recorded sweep rate, so the untouched book is worth what
    # a book that did nothing is worth — not a cent of what the policy wrote in.
    idle, _ = replay.run(company, lambda date, quotes, book: [])
    assert book["cash"] == idle["cash"] and not book["positions"]
    assert idle["cash"] < 100_100.0
    _, idle_navs = replay.run(company, lambda date, quotes, book: [])
    assert [row["nav"] for row in navs] == [row["nav"] for row in idle_navs]


def test_a_replayed_policy_lives_under_the_same_limits_as_the_advisors(company, logic):
    """Otherwise a replayed strategy beats the desk by being allowed more than it."""
    replay = logic(company, "replay")
    three_days(company)

    def all_in(date, quotes, book):
        return [{"action": "buy", "instrument": "SPY", "amount_usd": 90_000,
                 "reason": "everything on one thing"}]

    book, navs = replay.run(company, all_in)          # screened, like a real advisor
    spy = book["positions"].get("SPY", {"cost": 0.0})
    assert spy["cost"] <= 0.25 * 100_000 + 1, "the 25% concentration limit still binds"


# --------------------------------------------------------------------------
# What every other choice would have done.
# --------------------------------------------------------------------------

def test_the_grid_prices_every_choice_the_desk_did_not_make(company, logic):
    """Bandit feedback into full information, by subtraction rather than simulation."""
    replay = logic(company, "replay")
    three_days(company)
    grid = replay.counterfactual_grid(company, horizons=(1,))
    # 4 Sep -> 7 Sep is the next recorded day, and every price rose 2% that step.
    step = grid["2026-09-04"][1]
    assert len(step) == len(json.loads((company / "company/data/universe.json").read_text(encoding="utf-8"))["instruments"]), "every instrument, not only the ones traded"
    for symbol, moved in step.items():
        # The fixture rounds each price to six decimals, which is visible in the
        # returns of the instruments quoted in thousandths — JPYUSD trades near
        # 0.0067, so a rounded cent of it is a real fraction of a basis point.
        assert abs(moved - 0.02) < 5e-4, f"{symbol}: {moved}"


def test_a_horizon_that_runs_past_the_archive_is_absent_not_zero(company, logic):
    """A thesis that has not finished is not a thesis that failed."""
    replay = logic(company, "replay")
    three_days(company)
    grid = replay.counterfactual_grid(company, horizons=(1, 400))
    assert 400 not in grid["2026-09-04"]
    assert 1 in grid["2026-09-04"]


def test_a_horizon_lands_on_a_recorded_day_and_never_on_an_invented_one(company, logic):
    replay = logic(company, "replay")
    three_days(company)
    dates = ["2026-09-04", "2026-09-07", "2026-09-08"]
    # A Saturday the desk never ran resolves forward to the next day it did.
    assert replay._forward_date(dates, "2026-09-04", 1) == "2026-09-07"
    assert replay._forward_date(dates, "2026-09-04", 4) == "2026-09-08"
    assert replay._forward_date(dates, "2026-09-04", 90) is None


def test_an_order_is_scored_against_the_alternatives_it_beat(company, logic):
    """The comparison the archive can make for free, and a model cannot make at all."""
    replay = logic(company, "replay")
    three_days(company)
    orders = read(company, "company/data/orders/2026-09-04.json")["advisors"]
    gold = [o for o in orders["metals"]["orders"] if o["instrument"] == "XAUUSD"][0]
    assert gold["considered"][0]["instrument"] == "XAGUSD"

    scored = replay.score_decision(company, "2026-09-04",
                                   dict(gold, horizon_days=1))
    assert scored["scorable"]
    assert scored["asof"] == "2026-09-07"
    assert abs(scored["return"] - 0.02) < 1e-6
    assert len(scored["alternatives"]) == 1
    assert abs(scored["alternatives"][0]["return"] - 0.02) < 1e-6
    assert scored["of"] == 1


def test_a_decision_with_no_stated_horizon_is_unscorable_rather_than_scored_at_zero(
        company, logic):
    """Judging a thesis on a window it never claimed records slow ideas as bad ones."""
    replay = logic(company, "replay")
    three_days(company)
    out = replay.score_decision(company, "2026-09-04",
                                {"instrument": "SPY", "horizon_days": None})
    assert out["scorable"] is False and "horizon" in out["why"]


def test_every_scored_order_carries_the_conviction_it_was_sent_with(company, logic):
    """Stated confidence beside realised outcome — the calibration set, assembled."""
    replay = logic(company, "replay")
    three_days(company)
    scored = replay.score_all(company)
    assert scored, "the desk traded; something must be scorable"
    assert all("conviction" in row and "advisor" in row for row in scored)
    gold = [r for r in scored
            if r["advisor"] == "metals" and r["date"] == "2026-09-04"][0]
    assert gold["conviction"] == 0.7 and gold["horizon_days"] == 2
    assert gold["of"] == 1, "scored against the silver it was chosen over"
    # Orders whose horizon runs past the end of the archive are left out entirely
    # rather than scored early — momentum stated thirty days and there are three.
    assert not [r for r in scored if r["advisor"] == "momentum"]


def test_a_day_whose_file_will_not_parse_is_skipped_rather_than_guessed(company, logic):
    replay = logic(company, "replay")
    three_days(company)
    assert len(replay.load_series(company)) == 3
    (company / "company/data/prices/2026-09-07.json").write_text("{ broken",
                                                                 encoding="utf-8")
    assert len(replay.load_series(company)) == 2
