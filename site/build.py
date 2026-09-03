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
import json
import re
import shutil
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
    if held:
        kind = held.get("kind") if isinstance(held, dict) else "unreachable"
        why = (held.get("why") if isinstance(held, dict) else str(held)) or ""
        opening = {"unreachable": "Unreachable. No decision was recorded and the book "
                                  "was marked unchanged.",
                   "all_rejected": "Every order was refused.",
                   "chose_to_hold": "Held."}.get(kind, "Held.")
        return f"{opening} {why}".strip()
    parts = []
    for order in record.get("orders") or []:
        verb = "Bought" if order.get("action") == "buy" else "Sold"
        parts.append(f"{verb} ${order.get('amount_usd', 0):,.0f} of {order.get('instrument', '')}")
    tail = record.get("note") or ""
    return (" and ".join(parts) + ". " + tail).strip()


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

    (out / "view-standings.json").write_text(json.dumps(
        {"as_of": as_of, "day": len(dates), "rows": rows, "dates": dates,
         "series": series, "holds": holds, "record": record, "feed": feed},
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
        paragraphs = [p.strip() for p in body.split("\n\n")
                      if p.strip() and not p.strip().startswith(("#", "---", "|"))]
        if not paragraphs:
            return None
        return {"date": found[-1].stem[:10],
                "text": " ".join(paragraphs[0].split())[:700]}

    (out / "view-desk.json").write_text(json.dumps(
        {"as_of": as_of, "advisors": advisors, "staff": staff, "portraits": portraits,
         "review": latest_note("evaluator"), "letter": latest_note("chief")},
        ensure_ascii=False, indent=1), encoding="utf-8")


def _copy_json_tree(source, target):
    if source.exists():
        shutil.copytree(source, target)


def _latest(folder, suffix=".json"):
    files = sorted(p for p in folder.glob(f"*{suffix}")) if folder.exists() else []
    return files[-1] if files else None


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
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
