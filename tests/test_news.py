"""Facts arrive late or they do not arrive.

There is one asymmetry behind every test here. A price that shows up late is a
missing price: the desk notices, records the gap by provider name, and holds the
position at cost. A *fact* that shows up early is not a gap — it is an advisor
that knew tomorrow's filing this morning, trading brilliantly on it, and nothing
anywhere reporting a problem. The returns simply look good.

That is the failure this file exists to make impossible, and it is why the last
test walks the whole archive rather than one function: the property that matters
is not "the fence is implemented", it is "no decision ever recorded was shown
something it could not have known".
"""
import datetime as dt
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


def _item(**over):
    base = {"id": "x", "source": "sec_edgar", "kind": "8-K", "instrument": "AAPL",
            "published_utc": "2026-09-04T06:00:00+00:00", "anticipated": False,
            "headline": "something", "value": None, "url": None}
    base.update(over)
    return base


ASKED = "2026-09-04T06:23:00+00:00"


def test_an_item_published_after_the_question_is_never_shown(company, logic):
    """The whole point. This is what a leaked future looks like on the way in."""
    news = logic(company, "news")
    tomorrow = _item(id="future", published_utc="2026-09-05T06:00:00+00:00")
    assert news.visible([tomorrow], ASKED) == []


def test_an_item_published_in_the_same_second_is_not_shown_either(company, logic):
    """A filing accepted the instant the advisor was asked is a coin toss."""
    news = logic(company, "news")
    assert news.visible([_item(id="tie", published_utc=ASKED)], ASKED) == []
    earlier = _item(id="earlier", published_utc="2026-09-04T06:22:59+00:00")
    assert [i["id"] for i in news.visible([earlier], ASKED)] == ["earlier"]


def test_an_item_with_no_publication_instant_is_collected_and_never_shown(company, logic):
    """FRED's keyless feed gives observations, not releases.

    August's inflation figure is published in mid-September. Treating the
    observation date as the publication date would hand every advisor a month of
    hindsight on every macro item, so a missing instant means invisible rather than
    a guess at what it probably was.
    """
    news = logic(company, "news")
    macro = _item(id="fred:CPIAUCSL:2026-08-01", source="fred", instrument=None,
                  published_utc=None, value=322.1)
    assert news.visible([macro], ASKED) == []


def test_a_schedule_is_shown_because_a_schedule_is_not_news(company, logic):
    """That the committee meets on a date has been public for a year."""
    news = logic(company, "news")
    meeting = _item(id="fomc:2026-09-15", source="fomc_calendar", instrument=None,
                    published_utc=None, anticipated=True)
    assert [i["id"] for i in news.visible([meeting], ASKED)] == ["fomc:2026-09-15"]


def test_a_decision_with_no_recorded_instant_is_shown_nothing(company, logic):
    """Without an anchor there is no fence, and no fence means show nothing."""
    news = logic(company, "news")
    assert news.visible([_item()], None) == []
    assert news.visible([_item()], "") == []


def test_a_timestamp_that_will_not_parse_is_dropped_rather_than_repaired(company, logic):
    news = logic(company, "news")
    assert news._iso_instant("2026-09-01T22:32:04.000Z") == "2026-09-01T22:32:04+00:00"
    assert news._iso_instant("last Tuesday") is None
    assert news._iso_instant("") is None
    assert news._iso_instant(None) is None


def test_an_advisor_is_not_made_to_read_about_what_it_cannot_trade(company, logic):
    """Every line costs tokens on every call, on every advisor, every day."""
    news = logic(company, "news")
    universe = {"AAPL", "NVDA"}
    items = [_item(id="a", instrument="AAPL"), _item(id="b", instrument="BRK"),
             _item(id="c", instrument=None)]
    assert {i["id"] for i in news.for_advisor(items, universe)} == {"a", "c"}


def test_the_newest_items_are_the_ones_that_fit(company, logic):
    news = logic(company, "news")
    items = [_item(id=f"n{i}", published_utc=f"2026-09-0{i}T06:00:00+00:00")
             for i in range(1, 6)]
    kept = news.for_advisor(items, {"AAPL"}, limit=2)
    assert [i["id"] for i in kept] == ["n5", "n4"]


# --------------------------------------------------------------------------
# The archive, not the function.
# --------------------------------------------------------------------------

def test_the_whole_day_is_collected_even_though_most_of_it_is_not_shown(company):
    """The price book is recorded whole; so is this, and for the same reason.

    What was available and not shown is exactly what a later study needs — it is
    the control for what the advisor did with what it had.
    """
    run_day(company, "2026-09-04", "fri")
    day = read(company, "company/news/2026-09-04.json")
    assert len(day["items"]) == 5, "everything the desk could read"
    shown = read(company, "company/data/orders/2026-09-04.json")["advisors"]["momentum"]
    assert len(shown["news_shown"]) == 2, "and only what it was allowed to know"


def test_the_fixture_filing_from_the_future_reaches_nobody(company):
    """The mock deliberately contains a filing dated ten years out."""
    run_day(company, "2026-09-04", "fri")
    orders = read(company, "company/data/orders/2026-09-04.json")["advisors"]
    for advisor, record in orders.items():
        assert "edgar:0000000000-26-000002" not in record["news_shown"], advisor


def test_every_decision_in_the_archive_survives_the_look_ahead_audit(company, logic):
    """The invariant, over every decision ever recorded.

    A replay that stops reproducing the ledger is a bookkeeping bug and looks like
    one. A news item shown before it was published looks like an edge: the numbers
    improve and nothing complains. So the claim is checked against the record
    rather than trusted to the code that wrote it.
    """
    news = logic(company, "news")
    run_day(company, "2026-09-04", "fri")
    run_day(company, "2026-09-07", "mon")
    assert news.audit(company) == []


def test_the_audit_actually_catches_a_leak(company, logic):
    """A fence that cannot fail is a decoration.

    The record is edited to claim an advisor saw the future filing, which is what
    a real leak would look like on disk, and the audit has to name it.
    """
    news = logic(company, "news")
    run_day(company, "2026-09-04", "fri")
    path = company / "company/data/orders/2026-09-04.json"
    day = json.loads(path.read_text(encoding="utf-8"))
    day["advisors"]["momentum"]["news_shown"].append("edgar:0000000000-26-000002")
    path.write_text(json.dumps(day), encoding="utf-8")

    found = news.audit(company)
    assert len(found) == 1
    assert found[0]["advisor"] == "momentum"
    assert found[0]["item"] == "edgar:0000000000-26-000002"
    assert "published" in found[0]["why"]


def test_a_feed_that_breaks_in_a_way_nobody_predicted_does_not_stop_the_desk(company):
    """The one that matters if this is left running for a month.

    Prices are the desk; facts are a convenience. These three services have never
    been called from the runner, and the failure that costs a trading day is not
    the outage anybody wrote a handler for — it is the shape nobody has met. So
    the whole collection sits inside a net, and the day survives an outright
    crash in it with the reason written into the record.
    """
    news = company / "company/agents/logic/news.py"
    news.write_text(news.read_text(encoding="utf-8").replace(
        "def fetch(root, date):",
        "def fetch(root, date):\n"
        "    raise RuntimeError('the provider answered with something new')", 1),
        encoding="utf-8")

    result = run_day(company, "2026-09-04", "fri")
    assert result.returncode == 0, result.stderr

    day = read(company, "company/news/2026-09-04.json")
    assert day["items"] == []
    assert day["short"] and "something new" in day["short"][0]["why"]

    # And the part that pays the wages still happened.
    board = read(company, "company/data/leaderboard.json")
    assert len(board["rows"]) == 9
    orders = read(company, "company/data/orders/2026-09-04.json")["advisors"]
    assert any(rec["orders"] for rec in orders.values()), "the desk still traded"
    assert all(rec["news_shown"] == [] for rec in orders.values())


def test_the_audit_catches_a_decision_that_recorded_no_instant(company, logic):
    news = logic(company, "news")
    run_day(company, "2026-09-04", "fri")
    path = company / "company/data/orders/2026-09-04.json"
    day = json.loads(path.read_text(encoding="utf-8"))
    day["advisors"]["momentum"]["decided_utc"] = None
    path.write_text(json.dumps(day), encoding="utf-8")
    found = news.audit(company)
    assert found and all("decided_utc" in v["why"] or "publication" in v["why"]
                         for v in found)
