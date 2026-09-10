"""The site: that it builds, that it says what it must, and that it renders.

The third one is the point. The desk next door was green through five days of
serving four empty pages, because every check it had asked whether the HTML
balanced and none asked whether the JavaScript produced anything. `node --check`
would not have caught it either — the file parsed perfectly and did nothing.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ("index.html", "desk.html", "office.html", "changelog.html")


def build(root):
    return subprocess.run([sys.executable, "site/build.py"], cwd=root,
                          capture_output=True, text=True)


def trading_day(root, date="2026-09-04", day="fri"):
    """Give the fixture a day of real output. The empty desk is the default and
    the pages must survive it, but a page with nothing to draw cannot show whether
    it draws."""
    env = {"MOCK_LLM": "1", "MOCK_HTTP": "1", "SHIFT_DATE": date,
           "MOCK_ANSWERS": str(root / "tests/mock_answers.json"),
           "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(root)}
    subprocess.run([sys.executable, "kernel/runner.py", "--day", day],
                   cwd=root, env=env, capture_output=True, text=True)


def test_the_site_builds_from_an_opening_day_desk(company):
    result = build(company)
    assert result.returncode == 0, result.stderr
    data = company / "site/data"
    assert (data / "roster.json").exists()
    assert len(json.loads((data / "roster.json").read_text(encoding="utf-8"))) == 11
    assert len(list((data / "avatars").glob("*.svg"))) == 11
    assert (data / "manifest.json").exists()


def test_every_page_carries_the_sentences_that_make_it_honest(company):
    """The repository is called agent-capital and the pages are full of dollar
    figures. A visitor has three seconds to understand that none of it is real."""
    build(company)
    result = subprocess.run([sys.executable, "tests/check_html.py"], cwd=company,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_check_html_actually_fails_when_a_disclaimer_goes_missing(company):
    build(company)
    page = company / "site/index.html"
    page.write_text(page.read_text(encoding="utf-8")
                    .replace("No money is invested", "X"),
                    encoding="utf-8")
    result = subprocess.run([sys.executable, "tests/check_html.py"], cwd=company,
                            capture_output=True, text=True)
    assert result.returncode == 1 and "no money" in result.stdout.lower()


def test_the_hallway_prints_one_name_not_three(company):
    """The kernel writes the name; a model that signs its line writes it again."""
    sys.path.insert(0, str(company / "assets"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_under_test",
                                                  company / "site/build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.hallway_line(
        "Nadia Vance: Liam Zhou: The coffee machine may be gone.") \
        == "The coffee machine may be gone."
    assert module.hallway_line("Anton Weiss: Bought gold.") == "Bought gold."
    assert module.hallway_line("Anton Weiss: Note: bought gold.") == "Note: bought gold."


def test_the_record_itself_is_never_tidied(company):
    """Speaker prefixes come off the display. company/hallway keeps every word."""
    written = "Anton Weiss: Anton Weiss: Bought gold.\n"
    (company / "company/hallway/2026-09-04-metals.txt").write_text(
        written, encoding="utf-8")
    build(company)
    assert (company / "company/hallway/2026-09-04-metals.txt").read_text(
        encoding="utf-8") == written
    assert (company / "site/data/hallway/2026-09-04-metals.txt").read_text(
        encoding="utf-8").strip() == "Bought gold."


def test_the_wardrobe_cannot_invent_a_slot(company):
    """A look is chosen from a fixed schema; nobody grows a second nose."""
    sys.path.insert(0, str(company / "assets"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("avatars_under_test",
                                                  company / "assets/avatars.py")
    avatars = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(avatars)
    looks = json.loads((company / "company/agents/appearance.json").read_text(
        encoding="utf-8"))
    roster = json.loads((company / "company/roster.json").read_text(encoding="utf-8"))
    assert set(looks) == {a["id"] for a in roster}
    for who, slots in looks.items():
        assert set(slots) == set(avatars.SCHEMA), f"{who} has the wrong slots"
        for slot, value in slots.items():
            assert value in avatars.SCHEMA[slot], f"{who}.{slot} = {value!r}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on this machine")
def test_the_pages_have_everything_they_need_to_draw(company):
    """Not that app.js parses — that the seams between it and the data still meet.

    A page goes blank for three reasons and all three are silent in a browser:
    a file or key the build stopped publishing, an element id renamed on one side
    only, and a template the script clones that is not on the page using it.
    """
    # Two days, because a line needs two points and the chart is one of the
    # things being checked.
    trading_day(company, "2026-09-04", "fri")
    trading_day(company, "2026-09-07", "mon")
    build(company)
    result = subprocess.run(["node", "tests/render.js"], cwd=company,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on this machine")
def test_the_contract_check_is_not_hollow(company):
    """A key quietly dropped from a published file has to fail, or none of this counts."""
    trading_day(company, "2026-09-04", "fri")
    trading_day(company, "2026-09-07", "mon")
    build(company)
    view = company / "site/data/view-standings.json"
    doc = json.loads(view.read_text(encoding="utf-8"))
    del doc["series"]
    view.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run(["node", "tests/render.js"], cwd=company,
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "series" in result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on this machine")
def test_an_element_the_script_reaches_for_cannot_quietly_disappear(company):
    """The other half of the seam: markup renamed without the script following."""
    trading_day(company, "2026-09-04", "fri")
    build(company)
    page = company / "site/index.html"
    page.write_text(page.read_text(encoding="utf-8")
                    .replace('id="standings-body"', 'id="standings-rows"', 1),
                    encoding="utf-8")
    result = subprocess.run(["node", "tests/render.js"], cwd=company,
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "standings-body" in result.stderr


def test_the_changelog_only_carries_autonomous_merges(company):
    sys.path.insert(0, str(company / "assets"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_changelog",
                                                  company / "site/build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entries = module.changelog(company, ["desk", "chief", "evaluator"])
    assert all(e["message"].split(":")[0] in ("desk", "chief", "evaluator")
               for e in entries)


def test_the_holdings_history_lands_exactly_on_todays_books(company):
    """The pies under every advisor are rebuilt from the recorded orders, day by
    day. The last day of that rebuild must be the portfolio file as it stands, or
    the history on the page is a past that does not add up to the present."""
    trading_day(company, "2026-09-04", "fri")
    trading_day(company, "2026-09-07", "mon")
    assert build(company).returncode == 0
    view = json.loads((company / "site/data/view-standings.json").read_text(encoding="utf-8"))
    assert view["alloc"], "no holdings were published"
    for key, alloc in view["alloc"].items():
        assert alloc["history"], f"{key}: the recorded orders did not rebuild today's book"
        assert [d["date"] for d in alloc["days"]] == view["dates"]
        book = json.loads((company / f"company/data/portfolios/{key}.json")
                          .read_text(encoding="utf-8"))
        last = alloc["days"][-1]
        assert set(last["parts"]) == set(book["positions"]), key
        assert abs(last["cash"] - book["cash"]) < 0.05, key
        assert len(alloc["slots"]) <= 7


def test_a_book_that_does_not_replay_shows_only_today(company):
    """If the record and the book disagree, the page draws today and nothing else."""
    trading_day(company, "2026-09-04", "fri")
    trading_day(company, "2026-09-07", "mon")
    path = company / "company/data/portfolios/index.json"
    book = json.loads(path.read_text(encoding="utf-8"))
    book["cash"] = round(book["cash"] - 1234.0, 2)
    path.write_text(json.dumps(book), encoding="utf-8")
    assert build(company).returncode == 0
    view = json.loads((company / "site/data/view-standings.json").read_text(encoding="utf-8"))
    alloc = view["alloc"]["index"]
    assert alloc["history"] is False
    assert len(alloc["days"]) == 1
    assert abs(alloc["days"][0]["cash"] - book["cash"]) < 0.01


def test_no_page_prints_a_date_or_a_rewrite_nobody_recorded(company):
    """The redesign shipped with sample copy baked into the markup: a fixed
    "4 September", "since 7 August", and a brief rewrite for an advisor on a
    Sunday before the desk had opened. Article 6 — facts are not invented."""
    for page in PAGES:
        text = (company / "site" / page).read_text(encoding="utf-8")
        for stale in ("4 September", "7 August", "30 August", "Twenty-one days"):
            assert stale not in text, f"{page} still carries '{stale}'"
    app = (company / "site/app.js").read_text(encoding="utf-8")
    assert "7 August" not in app
