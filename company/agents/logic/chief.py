"""Sunday: the letter, the name if the company still has none, and once a month
the rewrite.

Three jobs in one shift because they belong to one person and they share the same
material: what the desk did, and what its record says about it. Splitting them
across three agents would mean fetching the same standings three times.

The shift degrades in a fixed order. If the rewrite cannot be produced or cannot be
published, the letter still goes out and the reason is recorded. If the letter
cannot be produced either, the shift fails honestly and the runner logs it. What
never happens is a rewrite landing without a record of why.
"""
import importlib.util
import json
from pathlib import Path

LETTER = ('ANSWER ONLY with this JSON object: '
          '{"letter": "<the Sunday letter, markdown, 200-400 words>", '
          '"company_name": <a name for the company, or null if it already has one>, '
          '"hallway": "<one line, or null>", "memory_add": "<one line, or null>"}')

REWRITE = ('ANSWER ONLY with this JSON object: '
           '{"brief": "<the complete rewritten brief, markdown, starting with a '
           '# heading>", "what_changed": "<two or three sentences naming exactly '
           'what you changed and which trades made you change it>"}')


def _logic(root, name):
    spec = importlib.util.spec_from_file_location(
        f"logic_{name}", Path(root) / "company/agents/logic" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(root, rel):
    path = Path(root) / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _json(root, rel, default):
    raw = _text(root, rel)
    try:
        return json.loads(raw) if raw else default
    except json.JSONDecodeError:
        return default


def _parse(raw, required):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
        text = text.strip()
    obj = json.loads(text)
    if not isinstance(obj, dict) or not isinstance(obj.get(required), str):
        raise ValueError(f"the answer has no usable {required!r}")
    return obj


def _board_text(board):
    if not board.get("rows"):
        return "  (no record yet)"
    return "\n".join(
        f"  {i:>2}. {r['name']:<20} {r['rol'] if 'rol' in r else r['mandate'][:34]:<36} "
        f"${r['nav']:>12,.2f}  {r['return_pct']:+7.2f}%  worst drawdown "
        f"{r['max_drawdown_pct']:.2f}%"
        for i, r in enumerate(board["rows"], 1))


def _name_the_company(root, chosen, files):
    """Write the chosen name into the constitution's first line. Once, ever."""
    path = "company/constitution.md"
    text = _text(root, path)
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Company name:"):
        return None
    if "not chosen" not in lines[0]:
        return None
    name = " ".join(str(chosen).split())[:60]
    if not name:
        return None
    lines[0] = f"Company name: {name}"
    files[path] = "\n".join(lines) + "\n"
    return name


def run(agent, ctx, chat, root):
    root = Path(root)
    date = ctx["date"]
    ledger, evolve = _logic(root, "ledger"), _logic(root, "evolve")
    desk = _logic(root, "desk")

    roster = json.loads((root / "company/roster.json").read_text(encoding="utf-8"))
    advisors = [a for a in roster if a.get("driven_by")]
    board = desk.leaderboard(root, advisors, date)
    files, notes = {}, []

    # ---- the letter ------------------------------------------------------
    user = (f"[DATE:{date}]\n\nTHE DESK\n{_board_text(board)}\n\n"
            f"THE COMPANY'S CONSTITUTION\n{_text(root, 'company/constitution.md')[:2500]}\n\n"
            f"YOUR NOTES\n{ctx['memory'] or '  (nothing yet)'}\n\n"
            f"THE FLOOR THIS WEEK\n{ctx['hallway'] or '  (quiet)'}\n\n{LETTER}")
    answer = _parse(chat(ctx["prompt"], user, want_json=True, root=root), "letter")

    named = None
    if answer.get("company_name"):
        named = _name_the_company(root, answer["company_name"], files)
        if named:
            notes.append(f"The company has a name: **{named}**.")

    # ---- the monthly rewrite --------------------------------------------
    record = None
    if evolve.due(root, date):
        record = _rewrite(root, date, advisors, board, chat, ctx, ledger, evolve, files)
        notes.append(record["headline"])

    body = [f"# {agent['ad']} — Sunday letter, {date}", ""]
    body += [answer["letter"].strip(), ""]
    if notes:
        body += ["## Desk business", ""] + [f"- {n}" for n in notes] + [""]
    body += ["---", "",
             "Every figure in this letter comes from a simulation. No money is "
             "invested, offered, received or managed here, and nothing in it is "
             "advice or a recommendation.", ""]
    files[f"company/minutes/{date}-chief.md"] = "\n".join(body)

    title = f"chief: sunday letter {date}"
    if named:
        title = f"chief: the company is called {named}"
    elif record and record["published"]:
        title = f"chief: {record['advisor']} brief rewritten, {date}"
    return {"files": files,
            "pr": {"title": title, "body": "\n".join(f"- {n}" for n in notes)
                   or "The weekly letter.", "draft": False},
            "hallway": answer.get("hallway"),
            "memory_add": answer.get("memory_add")}


def _rewrite(root, date, advisors, board, chat, ctx, ledger, evolve, files):
    """The month's one rewrite. Always returns a record, published or not."""
    rows, worst = evolve.standings(root, advisors, date, ledger)
    spread = evolve.diversity(root, advisors)
    state = {"last_run": date, "diversity": spread}
    stamp = lambda: files.update({evolve.STATE:
                                  json.dumps(state, ensure_ascii=False, indent=1) + "\n"})

    if not worst:
        state["outcome"] = "skipped"
        stamp()
        return {"advisor": None, "published": False,
                "headline": (f"No rewrite this month: no advisor has "
                             f"{evolve.MIN_ROWS} valuations inside the window yet.")}

    who = next(a for a in advisors if a["id"] == worst["advisor"])
    facts = evolve.evidence(root, who["id"], date)
    old = _text(root, f"company/agents/prompts/{who['id']}.md")
    ranking = "\n".join(
        f"  {r['name']:<20} {r['window_return_pct'] if r['window_return_pct'] is not None else '—':>8}"
        f"   ({r['rows']} valuations)" for r in
        sorted(rows, key=lambda r: (r["window_return_pct"] is None,
                                    r["window_return_pct"])))
    user = (
        f"[REWRITE][DATE:{date}][ADVISOR:{who['id']}]\n\n"
        f"{who['ad']} finished last over the trailing {evolve.WINDOW_DAYS} days: "
        f"{worst['window_return_pct']:+.2f}% across {worst['rows']} valuations. "
        f"Since opening: {worst['overall']['return_pct']:+.2f}%, worst drawdown "
        f"{worst['overall']['max_drawdown_pct']:.2f}%.\n\n"
        f"THE WHOLE DESK OVER THE SAME WINDOW\n{ranking}\n\n"
        f"WHAT {who['ad'].upper()} ACTUALLY DID\n"
        + ("\n".join(facts["placed"]) or "  (no orders at all)") + "\n\n"
        f"ORDERS THE DESK REFUSED\n"
        + ("\n".join(facts["refused"]) or "  (none)") + "\n\n"
        f"WHAT THEY SAID THEY WERE DOING\n"
        + ("\n".join(facts["notes"][-12:]) or "  (nothing recorded)") + "\n\n"
        f"THE BRIEF AS IT STANDS\n---\n{old}\n---\n\n"
        f"Rewrite it. Change the thing the evidence points at and leave the rest "
        f"alone, so that next month it is possible to tell which change mattered. "
        f"Risk limits are not in this file and cannot be moved from it.\n\n{REWRITE}")

    try:
        answer = _parse(chat(ctx["prompt"], user, want_json=True, root=root), "brief")
        refusal = evolve.acceptable(answer["brief"], old, who["ad"])
    except (ValueError, json.JSONDecodeError) as e:
        answer, refusal = None, f"{type(e).__name__}: {e}"

    if refusal or answer is None:
        state.update({"outcome": "refused", "advisor": who["id"], "why": refusal})
        stamp()
        return {"advisor": who["id"], "published": False,
                "headline": (f"{who['ad']} finished last "
                             f"({worst['window_return_pct']:+.2f}%) but the rewrite "
                             f"was refused: {refusal} The brief stands.")}

    new = answer["brief"].strip() + "\n"
    files[f"company/agents/prompts/{who['id']}.md"] = new
    files[f"company/evolution/{date}-{who['id']}.md"] = (
        f"# {who['ad']} — brief rewritten {date}\n\n"
        f"**Why this advisor:** last over the trailing {evolve.WINDOW_DAYS} days at "
        f"{worst['window_return_pct']:+.2f}%, across {worst['rows']} valuations. "
        f"That is a short run and the record says so.\n\n"
        f"**What the chief changed**\n\n{answer.get('what_changed', '').strip()}\n\n"
        f"**How alike the eight briefs are now:** {spread} "
        f"(1.0 would mean the desk has collapsed into one strategy)\n\n"
        f"**The desk over the window**\n\n```\n{ranking}\n```\n\n"
        f"**The diff**\n\n```diff\n{evolve.diff(old, new, who['id'])}```\n")
    state.update({"outcome": "published", "advisor": who["id"],
                  "window_return_pct": worst["window_return_pct"]})
    stamp()
    return {"advisor": who["id"], "published": True,
            "headline": (f"**{who['ad']}** finished last over the month "
                         f"({worst['window_return_pct']:+.2f}%) and their brief was "
                         f"rewritten. Diff and reasoning in "
                         f"`company/evolution/{date}-{who['id']}.md`. "
                         f"Brief similarity across the desk: {spread}.")}
