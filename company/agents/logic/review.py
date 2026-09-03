"""Friday: the week, marked.

The standings are already computed — the desk recomputes them from the NAV series
every day, and no model is involved in that. This shift does the part arithmetic
cannot: it reads what an advisor said it was doing against what its book shows it
did, and names the difference.

That is the finding worth publishing. Rank is noise at this length; drift is not.
An advisor whose brief says momentum and whose book has held a falling position for
three weeks is telling you something about briefs, which is the actual subject of
this company.
"""
import importlib.util
import json
from pathlib import Path

CONTRACT = ('ANSWER ONLY with this JSON object: '
            '{"output_markdown": "<your Friday note, markdown>", '
            '"hallway": "<one line to the floor, or null>", '
            '"memory_add": "<one line to yourself, or null>"}')


def _logic(root, name):
    spec = importlib.util.spec_from_file_location(
        f"logic_{name}", Path(root) / "company/agents/logic" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(root, rel, default):
    path = Path(root) / rel
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _bench(board):
    """The buy-and-hold row, if the desk has opened one."""
    return next((r for r in board.get("rows", []) if r.get("is_benchmark")), None)


def _summary(board):
    """Top and last among the advisors, and what the market did while they did it.

    Buy-and-hold is ranked in the table but it is not a colleague: calling it the
    week's top performer, or its worst, would be a category error in a sentence
    people read without opening the page.
    """
    ranked = [r for r in board.get("rows", []) if not r.get("is_benchmark")]
    if not ranked:
        return "Friday review."
    line = (f"Friday review. Top: {ranked[0]['name']} at "
            f"{ranked[0]['return_pct']:+.2f}%. Last: {ranked[-1]['name']} at "
            f"{ranked[-1]['return_pct']:+.2f}%.")
    bench = _bench(board)
    if bench:
        above = sum(1 for r in ranked if r["return_pct"] > bench["return_pct"])
        line += (f" Buy and hold: {bench['return_pct']:+.2f}%, with {above} of "
                 f"{len(ranked)} advisors above it.")
    return line


def _week(root, date, advisor_id):
    """Everything this advisor did in the last five recorded trading days."""
    folder = Path(root) / "company/data/orders"
    files = [p for p in sorted(folder.glob("*.json")) if p.stem <= date][-5:]
    lines = []
    for path in files:
        record = _json(root, path.relative_to(root).as_posix(), {}) \
            .get("advisors", {}).get(advisor_id)
        if not record:
            continue
        held = record.get("held")
        if held:
            # The Chief Investment Officer rewrites a brief using this list as the
            # argument. A day the model never answered is not evidence about the
            # advisor, and must not read like patience; a day every order was
            # refused is evidence, and a different kind from sending nothing.
            kind = held.get("kind") if isinstance(held, dict) else "unreachable"
            why = held.get("why", "") if isinstance(held, dict) else str(held)
            label = {"unreachable": "unreachable — no answer, not a decision",
                     "chose_to_hold": "chose to hold",
                     "all_rejected": "asked, every order refused"}.get(kind, kind)
            lines.append(f"  {path.stem}  {label}{(' — ' + why[:80]) if why else ''}")
            continue
        for order in record.get("orders", []):
            lines.append(f"  {path.stem}  {order['action']:<4} "
                         f"${order['amount_usd']:>9,.0f} {order['instrument']:<8} "
                         f"— {order.get('reason', '')[:110]}")
        if not record.get("orders"):
            lines.append(f"  {path.stem}  no orders — {record.get('note', '')[:110]}")
    return lines


def run(agent, ctx, chat, root):
    root = Path(root)
    date = ctx["date"]
    ledger = _logic(root, "ledger")
    roster = json.loads((root / "company/roster.json").read_text(encoding="utf-8"))
    advisors = [a for a in roster if a.get("driven_by")]

    prices = _json(root, f"company/data/prices/{date}.json", {"quotes": {}})["quotes"]
    board = _json(root, "company/data/leaderboard.json", {"rows": []})
    if not board.get("rows"):
        raise ValueError("there is no leaderboard yet; the desk has not run")

    blocks = []
    for row in board["rows"]:
        who = next((a for a in advisors if a["id"] == row["advisor"]), None)
        if not who:
            continue
        book = ledger.load(root, who["id"], opened=date)
        held = ledger.positions_view(book, prices)
        holdings = ", ".join(f"{h['instrument']} {h['return_pct']:+.1f}%"
                             for h in held) or "all cash"
        blocks.append(
            f"{row['name']} — {who['mandate']}\n"
            f"  NAV ${row['nav']:,.2f}  {row['return_pct']:+.2f}%  "
            f"worst drawdown {row['max_drawdown_pct']:.2f}%  "
            f"best day {row['best_day_pct']:+.2f}%  worst day {row['worst_day_pct']:+.2f}%\n"
            f"  holds: {holdings}\n"
            f"  cash ${book['cash']:,.2f}\n"
            f"  this week:\n" + ("\n".join(_week(root, date, who["id"])) or "    (nothing)"))

    user = (f"[DATE:{date}][DAY:{ctx['day']}]\n\n"
            f"Every advisor opened with ${ledger.OPENING_CASH:,.2f} on the same day, "
            f"trades the same instrument list under the same rules, and is priced "
            f"from the same file. The only difference between them is the brief.\n\n"
            f"THE DESK, BEST TO WORST\n\n" + "\n\n".join(blocks) + "\n\n"
            + (f"WHAT THE MARKET DID OVER THE SAME DAYS\n"
               f"  {_bench(board)['name']} — {_bench(board)['mandate']}\n"
               f"  NAV ${_bench(board)['nav']:,.2f}  "
               f"{_bench(board)['return_pct']:+.2f}%  "
               f"worst drawdown {_bench(board)['max_drawdown_pct']:.2f}%\n"
               f"  An advisor below this line was paid nothing to be worse than "
               f"buying everything and going away.\n\n" if _bench(board) else "")
            + f"YOUR NOTES\n{ctx['memory'] or '  (nothing yet)'}\n\n"
            f"THE FLOOR\n{ctx['hallway'] or '  (quiet)'}\n\n{CONTRACT}")

    raw = chat(ctx["prompt"], user, want_json=True, root=root)
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
        text = text.strip()
    answer = json.loads(text)
    if not isinstance(answer.get("output_markdown"), str):
        raise ValueError("the answer has no usable output_markdown")

    note = (f"# {agent['ad']} — week ending {date}\n\n"
            f"{answer['output_markdown'].strip()}\n\n"
            f"---\n\nA week is far too short a run to judge a strategy on, and the "
            f"figures above are a simulation. No money is invested, offered, "
            f"received or managed here, and nothing in this note is advice.\n")
    return {"files": {f"company/minutes/{date}-evaluator.md": note},
            "pr": {"title": f"evaluator: week ending {date}",
                   "body": _summary(board),
                   "draft": False},
            "hallway": answer.get("hallway"),
            "memory_add": answer.get("memory_add")}
