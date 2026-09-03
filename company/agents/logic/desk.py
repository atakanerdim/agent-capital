"""A trading day, start to finish, in one working tree.

The desk beside this one gives every colleague its own branch and its own pull
request, and that works because none of its colleagues need anything a colleague
produced that same morning. Here they do. Prices come first, eight advisors read
them, the book moves, and only then can the book be valued. Split across eight
branches cut from the same starting point, seven of them would be trading against
a price file that had not been merged yet.

So the day is one shift, one branch, one commit. Either the whole trading day
lands or none of it does, and there is no state in which the site can show orders
that were never priced or a valuation that predates the trades.

The order inside is fixed and it matters:

  1. fetch prices, and record what could not be fetched and why
  2. every advisor on the floor decides, against the book as it stands
  3. screened orders go through the book
  4. every book is marked to market, including the books of advisors who did
     nothing, because a portfolio moves on days its owner does not
  5. the leaderboard is recomputed from the NAV series

Step 4 is why the site cannot go quiet. It is arithmetic over a price file: no
model is consulted, nothing about it can refuse, and if every language model in
the chain is down all day the page still updates and simply says that nobody
traded. The advisors are the part that is allowed to fail.
"""
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path

CONTRACT = (
    'ANSWER ONLY with this JSON object and nothing else: '
    '{"orders": [{"action": "buy"|"sell", "instrument": "<id from the list>", '
    '"amount_usd": <number>, "reason": "<one sentence>", '
    '"conviction": <number between 0 and 1>, "horizon_days": <whole number of days>, '
    '"considered": [{"instrument": "<id you chose this one over>", '
    '"why_not": "<one short clause>"}]}], '
    '"note": "<two or three sentences on how you are reading the market today>", '
    '"hallway": "<one line to your colleagues, or null>", '
    '"memory_add": "<one short line to your future self, or null>"}\n'
    'An empty orders list is a real answer and often the right one. Holding is a '
    'decision; say so in the note.\n'
    'conviction is how sure you are about that one order, not how much you like the '
    'instrument: 0.5 means you would not be surprised either way, and if everything '
    'you send is a 0.9 the number stops carrying information. horizon_days is how '
    'long you expect to wait before the order is fairly judged. Neither number '
    'changes whether the order is accepted; they are recorded and compared against '
    'what actually happened.\n'
    'considered is the list of instruments on today\'s price list that you were '
    'genuinely choosing between and did not take — the ones this order beat. Leave '
    'it empty when there was no real alternative; an invented one is worse than '
    'none, because what every instrument did instead is computed from the record '
    'and compared against your reason for passing on it. At most five, and never '
    'the instrument you are actually buying.')


def _logic(root, name):
    spec = importlib.util.spec_from_file_location(
        f"logic_{name}", Path(root) / "company/agents/logic" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _kind(record):
    """The kind of a day record's `held`, or None when the book moved.

    Tolerates the older shape, where `held` was a bare string meaning unreachable,
    so a record written before this field was structured still reads correctly.
    """
    held = record.get("held")
    if not held:
        return None
    if isinstance(held, dict):
        return held.get("kind")
    return "unreachable"


def _held_kind(asked, accepted, rejected):
    """Why this advisor's book did not move, or None because it did.

    Three different events end a day with an unchanged portfolio and they mean
    opposite things about the advisor: it sent nothing (a decision), it sent
    something that risk refused in full (a misjudgement, and one the advisor is
    told about tomorrow), or it never answered at all (an outage, and nothing to do
    with the advisor). Recorded as one null field, a month of any of them reads as
    a month of patient conviction.
    """
    if accepted:
        return None
    if rejected:
        return {"kind": "all_rejected",
                "why": f"{len(rejected)} order(s) asked for, none reached the book"}
    if not asked:
        return {"kind": "chose_to_hold", "why": "the advisor sent no orders"}
    return {"kind": "all_rejected", "why": "the orders field held nothing usable"}


def _sha(root, rel):
    """A short fingerprint of a file that shapes a decision, or None if absent.

    A brief is rewritten once a month and a memory grows every day. When an
    advisor's behaviour changes, the question is always whether the market moved
    or the advisor did — and a date is a weak answer, because two rewrites can land
    on one day and a rewrite can take effect the day after it is committed. A hash
    of the exact text that was in force answers it exactly, and costs twelve
    characters a day.
    """
    path = Path(root) / rel
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _price_table(quotes):
    """The market as an advisor sees it: one line per instrument, grouped."""
    rows = {}
    for symbol, quote in sorted(quotes.items()):
        rows.setdefault(quote["class"], []).append(
            f"  {symbol:<8} {quote['close']:>12,.4f}  {quote['name']}")
    return "\n".join(f"{kind.upper()}\n" + "\n".join(lines)
                     for kind, lines in sorted(rows.items()))


def _book_table(book, positions):
    if not positions:
        return "  (no positions — the whole book is in cash)"
    return "\n".join(
        f"  {row['instrument']:<8} {row['qty']:>12,.4f} units  cost ${row['cost']:>11,.2f}  "
        f"now ${row['value']:>11,.2f}  {row['return_pct']:+.2f}%"
        + ("" if row["priced"] else "   (held at cost — no price today)")
        for row in positions)


def _yesterday(root, advisor, date):
    """What the desk told this advisor last time it asked for something it could not have.

    A rejection that is not read is a rejection that will be made again. The same
    lesson was learned next door: three attempts at the same broken rewrite is not
    a retry, it is the same dice thrown three times.
    """
    folder = Path(root) / "company/data/orders"
    files = sorted(p for p in folder.glob("*.json") if p.stem < date)
    if not files:
        return ""
    previous = _read_json(files[-1], {}).get("advisors", {}).get(advisor, {})
    refused = previous.get("rejected") or []
    if not refused:
        return ""
    lines = "\n".join(f"  - {item['why']}" for item in refused[:5])
    return (f"\nOrders of yours the desk refused on {files[-1].stem}, and why:\n"
            f"{lines}\nDo not send those again in the same shape.\n")


def _decide(chat, root, agent, advisor, ctx, quotes, book, positions, nav, leaderboard):
    """Ask one advisor what it wants to do. Returns (parsed, error_or_None)."""
    system = _read_text(root, f"company/agents/prompts/{advisor['id']}.md")
    memory = _read_text(root, f"company/agents/memory/{advisor['id']}.md")
    standing = (f"You are {advisor['ad']}, {advisor['rol']} on this desk.\n"
                f"Your mandate: {advisor.get('mandate', '')}\n")
    user = (
        f"[ADVISOR:{advisor['id']}][DATE:{ctx['date']}][DAY:{ctx['day']}]\n\n"
        f"{standing}\n"
        f"YOUR BOOK\n  cash ${book['cash']:,.2f}\n  net asset value ${nav:,.2f}\n"
        f"  started at $100,000.00 on {book.get('opened', '?')}\n"
        f"{_book_table(book, positions)}\n\n"
        f"THE DESK TODAY\n{leaderboard}\n\n"
        f"PRICES YOU MAY TRADE AT (USD; anything not listed has no price today "
        f"and cannot be traded)\n{_price_table(quotes)}\n\n"
        f"YOUR NOTES TO YOURSELF\n{memory or '  (nothing yet)'}\n"
        f"{_yesterday(root, advisor['id'], ctx['date'])}\n"
        f"HOW THIS DESK WORKS\n"
        f"  Long only. No borrowing, no shorting, no derivatives.\n"
        f"  One instrument may never exceed 25% of your book.\n"
        f"  At most 12 holdings and at most 5 orders in a day.\n"
        f"  Orders are in dollars, not shares. The smallest is $100.\n"
        f"  Selling more than you hold sells all of it; that is allowed and normal.\n\n"
        f"{CONTRACT}")
    raw = chat(ctx["house"] + "\n" + system, user, want_json=True, root=root)
    return _parse(raw)


def _parse(raw):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
        text = text.strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"the answer was not JSON: {e.msg} at line {e.lineno}"
    if not isinstance(obj, dict):
        return None, "the answer was not a JSON object"
    if not isinstance(obj.get("orders", []), list):
        return None, "orders was not a list"
    return obj, None


def _read_text(root, rel):
    path = Path(root) / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _leaderboard_text(board):
    if not board.get("rows"):
        return "  (the desk opened today; nobody has a record yet)"
    return "\n".join(
        f"  {i + 1:>2}. {row['name']:<18} ${row['nav']:>12,.2f}  {row['return_pct']:+7.2f}%"
        for i, row in enumerate(board["rows"]))


def leaderboard(root, advisors, date):
    """Rebuild the standings from the NAV series. Arithmetic only; never a model.

    Buy-and-hold stands in the table with everybody else, ranked on the same
    number. A benchmark kept in a footnote is a benchmark nobody reads, and the
    advisors are shown these standings every morning — being above or below the
    market is the fact most worth their knowing.
    """
    ledger = _logic(root, "ledger")
    rows = []
    for advisor in advisors:
        series = _read_json(ledger.nav_path(root, advisor["id"]), {"series": []})
        stats = ledger.series_stats(series)
        rows.append({"advisor": advisor["id"], "name": advisor["ad"],
                     "mandate": advisor.get("mandate", ""),
                     "is_benchmark": False, **stats})
    if ledger.portfolio_path(root, ledger.BENCHMARK_ID).exists():
        series = _read_json(ledger.nav_path(root, ledger.BENCHMARK_ID), {"series": []})
        rows.append({"advisor": ledger.BENCHMARK_ID, "name": ledger.BENCHMARK_NAME,
                     "mandate": ledger.BENCHMARK_MANDATE, "is_benchmark": True,
                     **ledger.series_stats(series)})
    rows.sort(key=lambda r: r["return_pct"], reverse=True)
    return {"date": date, "opening_cash": ledger.OPENING_CASH, "rows": rows}


def best_advisor(board):
    """The leading row that is an advisor. Buy-and-hold is in the table, not on the desk."""
    return next((r for r in board["rows"] if not r.get("is_benchmark")), None)


def run(agent, ctx, chat, root):
    root = Path(root)
    date = ctx["date"]
    market = _logic(root, "market")
    risk = _logic(root, "risk")
    ledger = _logic(root, "ledger")

    roster = json.loads((root / "company/roster.json").read_text(encoding="utf-8"))
    advisors = [a for a in roster if a.get("driven_by") == agent["id"]]
    on_floor = [a for a in advisors if ctx["day"] in a["gunler"]]

    # ---- 1. the market ---------------------------------------------------
    book_of_prices = market.prices(root, date)
    quotes = book_of_prices["quotes"]
    if not quotes:
        # Every provider for every instrument failed. There is nothing to value
        # against and nothing to trade at, so the day is recorded and abandoned
        # rather than written half-true.
        raise ValueError(
            "no instrument could be priced by any provider today; "
            f"first failure: {(book_of_prices['short'] or [{}])[0]}")

    files = {f"company/data/prices/{date}.json":
             json.dumps(book_of_prices, ensure_ascii=False, indent=1) + "\n"}

    # Opened once, on the first day the desk ever priced anything, and untouched
    # after that. It has to happen here rather than in a setup script: its opening
    # prices are this file, and any later opening would be buying with hindsight.
    ledger.open_benchmark(root, quotes, date)

    # ---- 2 and 3. the advisors, and the book ----------------------------
    standings = _leaderboard_text(leaderboard(root, advisors, date))
    day_record, hallway_lines = {}, []
    for advisor in on_floor:
        book = ledger.load(root, advisor["id"], opened=date)
        nav, _, _ = ledger.value(book, quotes)
        positions = ledger.positions_view(book, quotes)
        # Everything that shaped this decision, named before it is made: the price
        # book, the brief, the memory, and the size of the book being risked. An
        # order record without these can be read but cannot be attributed.
        seen = {"snapshot_id": book_of_prices["snapshot_id"],
                "prompt_sha": _sha(root, f"company/agents/prompts/{advisor['id']}.md"),
                "memory_sha": _sha(root, f"company/agents/memory/{advisor['id']}.md"),
                "nav_before": round(nav, 2)}
        try:
            answer, why = _decide(chat, root, agent, advisor, ctx, quotes, book,
                                  positions, nav, standings)
        except Exception as e:                      # a provider chain that fell over
            answer, why = None, f"{type(e).__name__}: {e}"[:200]
        if answer is None:
            # An advisor that cannot be reached holds. That is not a failure of the
            # day — a portfolio left alone is a portfolio with a position, and it
            # still gets valued below like everybody else's.
            #
            # But it is not the same event as an advisor that answered and chose to
            # hold, and the archive must not blur them: one is a silent model, the
            # other is a decision. Counting them together would make a fortnight of
            # provider outages look like a fortnight of patience.
            day_record[advisor["id"]] = {
                "orders": [], "rejected": [], "note": "", "schema_gaps": 0,
                "held": {"kind": "unreachable", "why": why}, **seen}
            continue

        accepted, rejected = risk.screen(answer.get("orders", []), book, quotes,
                                         {i["id"] for i in market.load_universe(root)},
                                         nav)
        ledger.execute(root, advisor["id"], accepted, date)
        asked = answer.get("orders", [])
        day_record[advisor["id"]] = {
            "orders": accepted, "rejected": rejected,
            "note": str(answer.get("note", ""))[:800],
            "schema_gaps": sum(1 for o in accepted
                               if o["conviction"] is None or o["horizon_days"] is None),
            "held": _held_kind(asked, accepted, rejected), **seen}

        if answer.get("hallway"):
            line = str(answer["hallway"]).strip().splitlines()[0][:200]
            files[f"company/hallway/{date}-{advisor['id']}.txt"] = \
                f"{advisor['ad']}: {line}\n"
            hallway_lines.append((advisor["ad"], line))
        if answer.get("memory_add"):
            existing = _read_text(root, f"company/agents/memory/{advisor['id']}.md")
            files[f"company/agents/memory/{advisor['id']}.md"] = (
                existing + f"\n- [{date}] {str(answer['memory_add']).strip()[:300]}\n")

    # ---- 4. value every book, including the ones nobody touched ---------
    for advisor in advisors:
        ledger.mark(root, advisor["id"], quotes, date)
    ledger.mark(root, ledger.BENCHMARK_ID, quotes, date)

    # ---- 5. the standings ------------------------------------------------
    board = leaderboard(root, advisors, date)
    files["company/data/leaderboard.json"] = \
        json.dumps(board, ensure_ascii=False, indent=1) + "\n"
    files[f"company/data/orders/{date}.json"] = json.dumps(
        {"date": date, "advisors": day_record}, ensure_ascii=False, indent=1) + "\n"

    # The ledger writes portfolios and NAV files to disk as it goes, so they are
    # already in the working tree; the shift commits everything it finds.
    files[f"company/minutes/{date}-desk.md"] = _minutes(
        agent, date, book_of_prices, day_record, board, hallway_lines)

    traded = sum(len(r["orders"]) for r in day_record.values())
    held = sum(1 for r in day_record.values() if _kind(r) == "unreachable")
    return {
        "files": files,
        "pr": {"title": f"desk: {date}",
               "body": (f"Trading day {date}. {book_of_prices['covered']} instruments "
                        f"priced, {traded} order(s) filled across {len(on_floor)} "
                        f"advisor(s)"
                        + (f", {held} unreachable and holding" if held else "")
                        + f". Best on the desk: {best_advisor(board)['name']} at "
                          f"{best_advisor(board)['return_pct']:+.2f}%."
                        if best_advisor(board) else "."),
               "draft": False},
        "hallway": None,
        "memory_add": (f"{date}: priced {book_of_prices['covered']}, {traded} order(s), "
                       f"{held} advisor(s) unreachable."),
    }


def _minutes(agent, date, priced, day_record, board, hallway_lines):
    """The day, written for somebody reading the record a year from now."""
    out = [f"# {agent['ad']} — trading day {date}", ""]
    out += [f"Priced {priced['covered']} instruments."]
    if priced["short"]:
        out += ["", "Instruments the feed could not reach today:"]
        for gap in priced["short"]:
            reasons = "; ".join(f"{t['source']}: {t['why']}" for t in gap["tried"]) \
                or "no provider configured"
            out.append(f"- **{gap['instrument']}** — {reasons}")
    out += ["", "## What the desk did", ""]
    for who, record in sorted(day_record.items()):
        kind = _kind(record)
        why = (record["held"] or {}).get("why", "") if kind else ""
        if kind == "unreachable":
            out.append(f"- **{who}** could not be reached and held. {why}")
            continue
        if kind == "all_rejected":
            out.append(f"- **{who}** asked, and the desk refused every order. {why}")
            continue
        if not record["orders"]:
            out.append(f"- **{who}** placed no orders. {record['note']}")
        else:
            deals = ", ".join(f"{o['action']} ${o['amount_usd']:,.0f} {o['instrument']}"
                              for o in record["orders"])
            out.append(f"- **{who}**: {deals}. {record['note']}")
        for refused in record["rejected"]:
            out.append(f"    - refused: {refused['why']}")
    if board.get("rows"):
        out += ["", "## Standing", "", "| # | Advisor | NAV | Return | Worst drawdown | Days |",
                "|---|---|---|---|---|---|"]
        for i, row in enumerate(board["rows"], 1):
            out.append(f"| {i} | {row['name']} | ${row['nav']:,.2f} | "
                       f"{row['return_pct']:+.2f}% | {row['max_drawdown_pct']:.2f}% | "
                       f"{row['days']} |")
    if hallway_lines:
        out += ["", "## Said in passing", ""]
        out += [f"- *{who}*: {line}" for who, line in hallway_lines]
    out += ["", "---", "",
            "Every figure above is a simulation. No money was invested, offered, "
            "received or managed, and nothing here is advice.", ""]
    return "\n".join(out)
