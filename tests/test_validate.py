"""A file this desk ships has to parse.

Ported from the desk next door, where the same module was written after that site
went dark twice — once because a rewrite came back cut in half, once because a
quote had turned into an escape and the file grew while it stopped working — and
extended a third time when a whole page arrived as a JSON string on one line.

There is no editor agent here, so nothing rewrites these files automatically yet.
The gate is kept anyway, because it is the cheapest true thing that can be said
about a file and because the first agent that does rewrite one should find the
fence already standing rather than have it built after the outage.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _validate():
    spec = importlib.util.spec_from_file_location(
        "logic_validate", ROOT / "company/agents/logic/validate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_file_the_desk_ships_parses():
    """Nothing that fails this gate may sit in main, whoever put it there."""
    targets = sorted(
        list((ROOT / "site").glob("*.js")) + list((ROOT / "site").glob("*.css"))
        + list((ROOT / "site").glob("*.html"))
        + [p for p in (ROOT / "company").rglob("*.json")])
    assert len(targets) > 8, "the site and the desk data should both be in here"
    broken = {p.relative_to(ROOT).as_posix(): _validate().check(p.name, p.read_text(
        encoding="utf-8")) for p in targets}
    assert not {k: v for k, v in broken.items() if v}


def test_a_page_sent_as_one_escaped_line_is_refused():
    real = (ROOT / "site/office.html").read_text(encoding="utf-8")
    assert _validate().check("office.html", real) is None
    escaped = real.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    said = _validate().check("office.html", escaped)
    assert said and "one line" in said


def test_an_attribute_quoted_with_a_backslash_is_refused():
    page = ('<!DOCTYPE html>\n<html>\n<head><title>x</title></head>\n<body>\n'
            '<main>\n<div class=\\"feed\\">hello</div>\n</main>\n</body>\n</html>\n')
    said = _validate().check("page.html", page)
    assert said and "backslash" in said


def test_a_stylesheet_that_lost_its_selector_is_refused():
    """Braces still balance; every colour on the site stops applying."""
    css = (ROOT / "site/style.css").read_text(encoding="utf-8")
    assert _validate().check("style.css", css) is None
    assert _validate().check("style.css", css.replace(":root{", "{", 1))


def test_a_script_with_an_unclosed_string_is_refused():
    """The real script passes, and the same script with one quote opened does not.

    The sabotage is appended rather than substituted so that it keeps working when
    the page is redesigned: an editor that rewrites every line of app.js must not
    also be able to retire the test that guards it.
    """
    js = (ROOT / "site/app.js").read_text(encoding="utf-8")
    assert _validate().check("app.js", js) is None
    assert _validate().check("app.js", js + '\nconst leak = "never closed;\n')


def test_broken_json_is_refused():
    assert _validate().check("x.json", '{"a": 1,}')
    assert _validate().check("x.json", '{"a": 1}') is None
