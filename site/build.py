"""Site data packager: copies company/ content into site/data.

Deterministic and offline. It makes no network call and no model call, which is
what lets the same command run in CI, on a laptop, and on every Pages deploy and
produce the same bytes.

It also does one thing that is not copying. The kernel writes a hallway line as
"<colleague>: <what they said>" and the page prints the colleague separately, off
the roster, so a model that signs its own line puts the name on the page twice —
and next door one of them once signed with the name of a colleague who did not
exist. Speaker prefixes come off here, at the point of display. What is in
company/hallway is left exactly as written, because that file is the record and a
record does not get tidied.
"""
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site/data"

sys.path.insert(0, str(ROOT / "assets"))
import avatars  # noqa: E402  (portrait parts; pure computation, no network)

# Two or three capitalised words in front of a colon, never one: "Note:" and
# "Week 35:" are things a colleague may legitimately open with; "Liam Zhou:" is not.
SPEAKER = re.compile(r"^\s*[A-Z][\w.'’-]*(?: [A-Z][\w.'’-]*){1,2}\s*:\s*")


def hallway_line(text):
    """One hallway line with any speaker prefixes stripped off the front."""
    line = " ".join(text.split("\n")[0].split())
    for _ in range(3):
        shorter = SPEAKER.sub("", line, count=1)
        if shorter == line or not shorter:
            break
        line = shorter
    return line


def roster_public(root):
    """Publish the desk as people: kernel schema, identity and wardrobe, merged."""
    rows = json.loads((root / "company/roster.json").read_text(encoding="utf-8"))
    people = {p["id"]: p for p in json.loads(
        (root / "company/agents/identity.json").read_text(encoding="utf-8"))}
    out = []
    for r in rows:
        who = people.get(r["id"], {})
        out.append({"id": r["id"], "name": who.get("person", r["ad"]),
                    "title": who.get("title", r["rol"]), "room": who.get("room", "The floor"),
                    "bio": who.get("bio", ""), "role": r["rol"], "shifts": r["gunler"],
                    "mandate": r.get("mandate", ""),
                    "advisor": bool(r.get("driven_by"))})
    return out


def changelog(root, agent_ids):
    """Only autonomous merges belong on the public changelog."""
    prefixes = tuple(f"{a}: " for a in agent_ids) + ("desk: ", "chief: ", "evaluator: ")
    entries = []
    try:
        out = subprocess.run(["git", "log", "-n", "400", "--pretty=format:%as%x09%s"],
                             cwd=root, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return entries
    for line in out.splitlines():
        date, _, subject = line.partition("\t")
        if subject.startswith(prefixes):
            entries.append({"date": date, "message": subject})
    return entries


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _outcome(record):
    """What a day did to one book, in one word. The four are not interchangeable."""
    held = record.get("held")
    if held:
        kind = held.get("kind") if isinstance(held, dict) else "unreachable"
        return {"unreachable": "unreachable", "all_rejected": "refused",
                "chose_to_hold": "held"}.get(kind, "held")
    return "moved" if record.get("orders") else "held"


def _decision_line(date, record):
    """One sentence a reader can follow, built from what the day actually recorded."""
    held = record.get("held")
    note = (record.get("note") or "").strip()
    if held:
        kind = held.get("kind") if isinstance(held, dict) else "unreachable"
        why = (held.get("why") if isinstance(held, dict) else str(held)) or ""
        opening = {"unreachable": "Unreachable. No decision was recorded and the book "
                                  "was marked unchanged.",
                   "all_rejected": "Every order was refused.",
                   "chose_to_hold": "Held."}.get(kind, "Held.")
        if kind == "chose_to_hold" and why == "the advisor sent no orders":
            why = note  # the advisor's own reason says more than the desk's default
        return f"{opening} {why}".strip()
    parts = []
    for order in record.get("orders") or []:
        verb = "bought" if order.get("action") == "buy" else "sold"
        parts.append(f"{verb} ${order.get('amount_usd', 0):,.0f} of {order.get('instrument', '')}")
    said = (", ".join(parts[:-1]) + " and " + parts[-1]) if len(parts) > 1 else "".join(parts)
    said = said[:1].upper() + said[1:]
    return (said + ". " + note).strip()

def _logic(root, name):
    spec = importlib.util.spec_from_file_location(
        f"site_logic_{name}", Path(root) / "company/agents/logic" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Colour slots a pie can give out before the rest of a book folds into "Other".
PIE_SLOTS = 7


def allocations(root, rows, dates):
    """What every book held at every close, rebuilt from the record.

    A portfolio file only knows today. The mix a book carried last Tuesday is not
    stored anywhere, but it does not need to be: the orders the desk accepted and
    the prices it recorded are both on disk, and pushing the one through the
    desk's own `risk.apply_order` gives it back exactly (article 12 is the promise
    that this works). Each close is valued at that day's recorded price, or at cost
    when there was none, the same rule the ledger uses.

    If the rebuilt book does not land on the portfolio file as it stands today,
    the history is not published — only today's mix, read straight from the file.
    A pie of a past that does not add up to the present is an invented fact.
    """
    data = root / "company/data"
    try:
        risk = _logic(root, "risk")
        opening = _logic(root, "ledger").OPENING_CASH
    except Exception:  # noqa: BLE001 — the site must build even if logic moved
        return {}
    quotes = {d: _read_json(data / "prices" / f"{d}.json", {}).get("quotes") or {}
              for d in dates}
    orders = {d: _read_json(data / "orders" / f"{d}.json", {}).get("advisors") or {}
              for d in dates}

    def worth(positions, prices):
        parts = {}
        for symbol, held in positions.items():
            close = (prices.get(symbol) or {}).get("close")
            value = held["qty"] * float(close) if close and float(close) > 0 \
                else held.get("cost", 0.0)
            parts[symbol] = round(value, 2)
        return parts

    out = {}
    for row in rows:
        key = row["advisor"]
        actual = _read_json(data / "portfolios" / f"{key}.json", None)
        if not actual:
            continue
        days, replayed = [], True
        if key == "benchmark" or actual.get("frozen"):
            # Bought once on day one and never touched: the holdings are the file's.
            for d in dates:
                days.append({"date": d, "cash": round(actual.get("cash", 0.0), 2),
                             "parts": worth(actual.get("positions") or {}, quotes[d])})
        else:
            book = {"cash": float(opening), "positions": {}}
            for d in dates:
                for order in (orders[d].get(key) or {}).get("orders") or []:
                    risk.apply_order(book, order)
                book["cash"] = round(book["cash"], 2)
                for held in book["positions"].values():
                    held["qty"] = round(held["qty"], 8)
                    held["cost"] = round(held["cost"], 2)
                days.append({"date": d, "cash": book["cash"],
                             "parts": worth(book["positions"], quotes[d])})
            want = actual.get("positions") or {}
            replayed = (abs(book["cash"] - float(actual.get("cash", 0.0))) < 0.05
                        and set(want) == set(book["positions"])
                        and all(abs(want[s]["qty"] - book["positions"][s]["qty"]) < 1e-6
                                for s in want))
            if not replayed:
                last = dates[-1] if dates else ""
                days = [{"date": last, "cash": round(actual.get("cash", 0.0), 2),
                         "parts": worth(want, quotes.get(last, {}))}]
        peak = {}
        for day in days:
            total = day["cash"] + sum(day["parts"].values()) or 1.0
            for symbol, value in day["parts"].items():
                peak[symbol] = max(peak.get(symbol, 0.0), value / total)
        slots = sorted(peak, key=lambda s: (-peak[s], s))[:PIE_SLOTS]
        out[key] = {"slots": slots, "days": days, "history": replayed}
    return out


def views(root, out, roster):
    """The four files the pages actually read.

    The site is a monitoring surface, not a tour of the machinery, so each view
    gets one file shaped for the thing it draws rather than a pile of raw company
    records to reassemble in the browser. Everything here is derived — nothing is
    computed twice, and nothing appears on a page that is not already on disk.
    """
    data = root / "company/data"
    orders_dir, nav_dir = data / "orders", data / "nav"
    board = _read_json(data / "leaderboard.json", {"rows": []})
    rows = board.get("rows") or []
    by_id = {p["id"]: p for p in roster}

    order_days = sorted(orders_dir.glob("*.json")) if orders_dir.exists() else []
    as_of = order_days[-1].stem if order_days else ""

    # NAV series, one row per weekday, aligned on the dates the desk actually ran.
    series, dates = {}, []
    seen = set()
    for row in rows:
        points = _read_json(nav_dir / f"{row['advisor']}.json", {"series": []}).get("series") or []
        series[row["advisor"]] = [float(p["nav"]) for p in points]
        for point in points:
            if point["date"] not in seen:
                seen.add(point["date"])
                dates.append(point["date"])
    dates.sort()

    # What each book did on each of those days, and its largest holdings today.
    record, holds = {}, {}
    history = {path.stem: _read_json(path, {}).get("advisors") or {} for path in order_days}
    letters = {"moved": "m", "held": "h", "refused": "r", "unreachable": "u"}
    prices = _read_json(data / "prices" / f"{as_of}.json", {"quotes": {}}).get("quotes", {}) \
        if as_of else {}
    for row in rows:
        key = row["advisor"]
        record[key] = "".join(
            letters[_outcome(history[d][key])] for d in dates if key in history.get(d, {}))
        book = _read_json(data / "portfolios" / f"{key}.json", {"positions": {}})
        sized = []
        for symbol, held in (book.get("positions") or {}).items():
            price = (prices.get(symbol) or {}).get("close")
            worth = held["qty"] * float(price) if price else held.get("cost", 0.0)
            cost = held.get("cost", 0.0)
            sized.append({"instrument": symbol, "value": round(worth, 2),
                          "return_pct": round((worth / cost - 1) * 100, 2) if cost else 0.0})
        sized.sort(key=lambda h: h["value"], reverse=True)
        holds[key] = [{"instrument": h["instrument"], "return_pct": h["return_pct"]}
                      for h in sized[:3]]

    # How much of the market the desk could actually see on its last day. An
    # unattended month fails quietly — a provider starts refusing, the instruments
    # sit at cost, the books stop moving and the page still looks alive. This is
    # the number that gives that away.
    priced = _read_json(data / "prices" / f"{as_of}.json", {}) if as_of else {}
    feed = {"covered": len(priced.get("quotes") or {}),
            "universe": len(priced.get("quotes") or {}) + len(priced.get("short") or []),
            "short": [s.get("instrument") for s in (priced.get("short") or [])][:12]}

    alloc = allocations(root, rows, dates)
    universe = {i["id"]: i for i in (_read_json(data / "universe.json", {})
                                     .get("instruments") or [])}
    held_ever = sorted({s for a in alloc.values() for d in a["days"] for s in d["parts"]})
    instruments = {s: {"name": (universe.get(s) or {}).get("name", s),
                       "class": (universe.get(s) or {}).get("class", "")} for s in held_ever}

    (out / "view-standings.json").write_text(json.dumps(
        {"as_of": as_of, "day": len(dates), "rows": rows, "dates": dates,
         "series": series, "holds": holds, "record": record, "feed": feed,
         "alloc": alloc, "instruments": instruments},
        ensure_ascii=False, indent=1), encoding="utf-8")

    today = history.get(as_of, {})
    entries = [dict(rec, advisor=key) for key, rec in sorted(today.items())]
    (out / "view-today.json").write_text(json.dumps(
        {"as_of": as_of, "entries": entries}, ensure_ascii=False, indent=1), encoding="utf-8")

    books = {}
    for row in rows:
        key = row["advisor"]
        book = _read_json(data / "portfolios" / f"{key}.json", None)
        if not book:
            continue
        positions = []
        for symbol, held in sorted((book.get("positions") or {}).items()):
            price = (prices.get(symbol) or {}).get("close")
            priced = bool(price and float(price) > 0)
            worth = held["qty"] * float(price) if priced else held.get("cost", 0.0)
            cost = held.get("cost", 0.0)
            positions.append({"instrument": symbol, "qty": round(held["qty"], 6),
                              "cost": round(cost, 2), "value": round(worth, 2),
                              "priced": priced,
                              "return_pct": round((worth / cost - 1) * 100, 2) if cost else 0.0})
        decisions = []
        for date in reversed(dates):
            rec = history.get(date, {}).get(key)
            if rec:
                decisions.append({"date": date, "text": _decision_line(date, rec)})
            if len(decisions) >= 6:
                break
        person = by_id.get(key, {})
        books[key] = {
            "advisor": key, "name": row["name"], "mandate": row.get("mandate", ""),
            "nav": row["nav"], "cash": round(book.get("cash", 0.0), 2),
            "invested": round(row["nav"] - book.get("cash", 0.0), 2),
            "return_pct": row["return_pct"], "max_drawdown_pct": row["max_drawdown_pct"],
            "days": row["days"], "positions": positions,
            "record": [{"m": "moved", "h": "held", "r": "refused", "u": "unreachable"}[c]
                       for c in record.get(key, "")],
            "decisions": decisions, "title": person.get("title", "")}
    (out / "view-advisor.json").write_text(json.dumps(
        {"as_of": as_of, "books": books}, ensure_ascii=False, indent=1), encoding="utf-8")

    def initials(name):
        parts = [w for w in str(name).split() if w]
        return ("".join(w[0] for w in parts[:2]) or "?").upper()

    portraits = {}
    for person in roster:
        avatar = out / "avatars" / f"{person['id']}.svg"
        portraits[person["id"]] = {
            "initials": initials(person["name"]),
            "src": f"data/avatars/{person['id']}.svg" if avatar.exists() else None}

    def one_line(text):
        first = str(text).split(". ")[0].strip()
        return first + "." if first and not first.endswith(".") else first

    advisors = [{"advisor": p["id"], "name": p["name"], "role": p["title"],
                 "mandate": p.get("mandate", ""), "character": one_line(p.get("bio", ""))}
                for p in roster if p.get("advisor")]
    staff = [{"key": p["id"], "name": p["name"], "role": "Does not trade",
              "mandate": p.get("bio", ""), "character": p.get("title", "")}
             for p in roster if not p.get("advisor")]
    # The two pieces of writing the desk produces about itself. Taken from the
    # minutes as written; the page shows nothing at all rather than a placeholder
    # when a week has not produced one yet, because an invented quotation from an
    # evaluator who never said it is the one thing this record cannot survive.
    def latest_note(suffix):
        folder = root / "company/minutes"
        found = sorted(folder.glob(f"*-{suffix}.md")) if folder.exists() else []
        if not found:
            return None
        body = found[-1].read_text(encoding="utf-8")
        body = body.split("\n## Desk business")[0].split("\n---")[0]
        paragraphs = []
        for block in body.split("\n\n"):
            text = " ".join(block.split())
            # Headings, lists, tables and a lone bold line are the letter's
            # scaffolding. Printed on their own they read as "**What we did**".
            if not text or text.startswith(("#", "---", "|", "- ", "* ")):
                continue
            if re.fullmatch(r"\*\*[^*]+\*\*:?", text):
                continue
            paragraphs.append(re.sub(r"\*\*([^*]+)\*\*|\*([^*]+)\*",
                                     lambda m: m.group(1) or m.group(2), text))
        if not paragraphs:
            return None
        return {"date": found[-1].stem[:10], "text": paragraphs[0][:900]}

    def latest_rewrite():
        """The month's rewritten brief, as the chief recorded it — or nothing."""
        folder = root / "company/evolution"
        found = sorted(folder.glob("*.md")) if folder.exists() else []
        if not found:
            return None
        body = found[-1].read_text(encoding="utf-8")
        stem = found[-1].stem
        advisor = stem[11:]
        why = re.search(r"\*\*Why this advisor:\*\*\s*(.+)", body)
        changed = re.search(r"\*\*What the chief changed\*\*\s*\n\n(.+?)\n\n\*\*", body, re.S)
        person = by_id.get(advisor, {})
        return {"date": stem[:10], "advisor": advisor,
                "name": person.get("name", advisor), "title": person.get("title", ""),
                "why": " ".join(why.group(1).split()) if why else "",
                "changed": " ".join(changed.group(1).split())[:900] if changed else ""}

    (out / "view-desk.json").write_text(json.dumps(
        {"as_of": as_of, "advisors": advisors, "staff": staff, "portraits": portraits,
         "review": latest_note("evaluator"), "letter": latest_note("chief"),
         "rewrite": latest_rewrite()},
        ensure_ascii=False, indent=1), encoding="utf-8")


def _clear(path):
    """Remove the previous build. On Windows a directory carrying the read-only
    attribute refuses rmdir with "Access is denied" even when empty; clear the
    flag first. POSIX is left alone: S_IWRITE there would strip read and execute."""
    if os.name == "nt":
        for item in (path, *path.rglob("*")):
            try:
                os.chmod(item, stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(path)


def _copy_json_tree(source, target):
    if source.exists():
        shutil.copytree(source, target)


def _latest(folder, suffix=".json"):
    files = sorted(p for p in folder.glob(f"*{suffix}")) if folder.exists() else []
    return files[-1] if files else None


def main():
    if OUT.exists():
        _clear(OUT)
    OUT.mkdir(parents=True)

    data = ROOT / "company/data"
    for name in ("nav", "portfolios", "prices", "orders"):
        _copy_json_tree(data / name, OUT / name)
    # universe.json and sources.json are deliberately not published. They are the
    # desk's plumbing — which instruments, which providers, under what symbol — and
    # the site is a monitoring surface for a firm, not a tour of its wiring. They
    # stay in the repository, where the record belongs.
    for name in ("leaderboard.json", "evolution.json"):
        if (data / name).exists():
            shutil.copy(data / name, OUT / name)

    # The pages want today's two files without having to guess a filename.
    for folder, alias in (("prices", "prices-latest.json"), ("orders", "orders-latest.json")):
        newest = _latest(data / folder)
        if newest:
            shutil.copy(newest, OUT / alias)

    if (ROOT / "company/minutes").exists():
        shutil.copytree(ROOT / "company/minutes", OUT / "minutes")
    if (ROOT / "company/evolution").exists():
        shutil.copytree(ROOT / "company/evolution", OUT / "evolution")
        newest = _latest(ROOT / "company/evolution", ".md")
        if newest:
            shutil.copy(newest, OUT / "evolution-latest.md")
    if (ROOT / "company/hallway").exists():
        (OUT / "hallway").mkdir(parents=True, exist_ok=True)
        for src in sorted((ROOT / "company/hallway").glob("*.txt")):
            (OUT / "hallway" / src.name).write_text(
                hallway_line(src.read_text(encoding="utf-8")) + "\n", encoding="utf-8")

    shutil.copytree(ROOT / "company/agents/prompts", OUT / "prompts")
    shutil.copy(ROOT / "company/constitution.md", OUT / "constitution.md")
    avatars.write_all(OUT / "avatars", ROOT)

    roster = roster_public(ROOT)
    (OUT / "roster.json").write_text(
        json.dumps(roster, ensure_ascii=False, indent=1), encoding="utf-8")

    name = ""
    for line in (ROOT / "company/constitution.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("Company name:") and "not chosen" not in line:
            name = line.split(":", 1)[1].strip()
    (OUT / "name.txt").write_text(name, encoding="utf-8")

    (OUT / "changelog.json").write_text(
        json.dumps(changelog(ROOT, [r["id"] for r in roster]), ensure_ascii=False),
        encoding="utf-8")

    views(ROOT, OUT, roster)

    files = sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file())
    (OUT / "manifest.json").write_text(json.dumps(
        {"generated": dt.datetime.utcnow().isoformat(timespec="seconds"), "files": files},
        ensure_ascii=False), encoding="utf-8")
    print(f"site/data ready: {len(files)} files")


if __name__ == "__main__":
    main()
