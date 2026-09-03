"""Sunday, and the shape of the company that has to hold whatever the models say.

Three things happen on this shift and they degrade in a fixed order: the rewrite
may fail and the letter still goes out; the letter may fail and the shift fails
honestly. What must never happen is a brief changing without a record of why.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest


def sunday(company, date="2026-09-20"):
    env = {"MOCK_LLM": "1", "MOCK_HTTP": "1", "SHIFT_DATE": date,
           "MOCK_ANSWERS": str(company / "tests/mock_answers.json"),
           "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(company)}
    return subprocess.run([sys.executable, "kernel/runner.py", "--day", "sun"],
                          cwd=company, env=env, capture_output=True, text=True)


def month_of_valuations(company, worst="index"):
    import datetime as dt
    day = dt.date(2026, 8, 24)
    roster = json.loads((company / "company/roster.json").read_text(encoding="utf-8"))
    for i, advisor in enumerate(a for a in roster if a.get("driven_by")):
        rows, nav = [], 100_000.0
        for n in range(14):
            nav *= 1 - 0.004 if advisor["id"] == worst else 1 + 0.001 * (i + 1)
            rows.append({"date": (day + dt.timedelta(days=n)).isoformat(),
                         "nav": round(nav, 2), "cash": 0.0, "invested": round(nav, 2)})
        path = company / "company/data/nav" / f"{advisor['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"advisor": advisor["id"], "series": rows}),
                        encoding="utf-8")


def test_the_chief_names_the_company_once_and_only_once(company):
    assert sunday(company).returncode == 0
    first = (company / "company/constitution.md").read_text(
        encoding="utf-8").splitlines()[0]
    assert first == "Company name: Kestrel Line Research"
    (company / "company/data/evolution.json").unlink(missing_ok=True)
    assert sunday(company, "2026-10-04").returncode == 0
    assert (company / "company/constitution.md").read_text(
        encoding="utf-8").splitlines()[0] == first


def test_the_letter_goes_out_even_with_nothing_to_rewrite(company):
    """No advisor has a month of valuations yet; the shift still delivers."""
    assert sunday(company).returncode == 0
    note = (company / "company/minutes/2026-09-20-chief.md").read_text(encoding="utf-8")
    assert "No rewrite this month" in note
    assert "is a simulation" in note or "No money is invested" in note


def test_a_month_of_evidence_produces_a_rewrite_with_its_reasoning(company):
    month_of_valuations(company, worst="index")
    before = (company / "company/agents/prompts/index.md").read_text(encoding="utf-8")
    assert sunday(company).returncode == 0

    after = (company / "company/agents/prompts/index.md").read_text(encoding="utf-8")
    assert after != before, "the last-placed brief should have been rewritten"

    records = list((company / "company/evolution").glob("*.md"))
    assert len(records) == 1
    record = records[0].read_text(encoding="utf-8")
    for required in ("Grace Okonkwo", "Why this advisor", "What the chief changed",
                     "```diff", "How alike the eight briefs are now"):
        assert required in record, f"the record does not say: {required}"

    state = json.loads((company / "company/data/evolution.json").read_text(
        encoding="utf-8"))
    assert state["outcome"] == "published" and state["advisor"] == "index"


def test_a_brief_never_changes_without_a_record(company):
    month_of_valuations(company, worst="metals")
    before = {p.name: p.read_text(encoding="utf-8")
              for p in (company / "company/agents/prompts").glob("*.md")}
    sunday(company)
    after = {p.name: p.read_text(encoding="utf-8")
             for p in (company / "company/agents/prompts").glob("*.md")}
    changed = [name for name in before if before[name] != after[name]]
    records = list((company / "company/evolution").glob("*.md"))
    state = json.loads((company / "company/data/evolution.json").read_text(
        encoding="utf-8"))
    if state["outcome"] == "published":
        assert len(changed) == 1 and len(records) == 1
    else:
        assert not changed and not records


def test_a_refused_rewrite_leaves_the_brief_standing_and_says_so(company):
    """The fixture rewrite names Grace; make somebody else last and it must not land."""
    month_of_valuations(company, worst="metals")
    before = (company / "company/agents/prompts/metals.md").read_text(encoding="utf-8")
    assert sunday(company).returncode == 0
    assert (company / "company/agents/prompts/metals.md").read_text(
        encoding="utf-8") == before
    state = json.loads((company / "company/data/evolution.json").read_text(
        encoding="utf-8"))
    assert state["outcome"] == "refused" and "never names Anton" in state["why"]
    note = (company / "company/minutes/2026-09-20-chief.md").read_text(encoding="utf-8")
    assert "refused" in note


def test_at_most_one_rewrite_a_month(company):
    """Seven briefs untouched every month are the control the eighth is read against."""
    month_of_valuations(company, worst="index")
    sunday(company, "2026-09-20")
    sunday(company, "2026-09-27")
    assert len(list((company / "company/evolution").glob("*.md"))) == 1
