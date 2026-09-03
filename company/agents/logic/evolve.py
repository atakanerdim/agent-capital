"""Once a month, the last-placed advisor's brief is rewritten from its own losses.

This is the closest thing here to learning, and it is worth being exact about what
it is and what it is not.

It is not reinforcement learning. No weights move. The model is whatever the free
tier is serving that week and it has no memory of this desk beyond what is written
into its prompt. Calling this "fine-tuning" would be a lie of the kind this project
exists to avoid.

What it is: a measured reward signal, attached to the one thing about an advisor
that can actually change. An advisor is a brief. The brief produces trades, the
trades produce a return, and the return is a number nobody can argue with — eight
advisors, identical starting capital, identical instrument list, identical rules,
published daily. Once a month the worst of those numbers causes its own brief to be
rewritten, by a colleague who has been handed the trades that produced it. That is
a feedback loop with a real reward and a real actuator. It is evolutionary rather
than gradient: slow, high-variance, and legible, because every step is a diff and a
written reason sitting in `company/evolution/`.

Three fences, and the reason for each:

**A month, not a week.** A week of returns is mostly noise, and a loop that chases
noise will spend the year rewriting whoever was unlucky on Thursday. A month is not
enough either — nothing about a month is statistically respectable — but it is the
shortest window where a strategy can be said to have had a bad *run* rather than a
bad *day*, and the record makes the sample size visible so nobody is fooled.

**One advisor.** Rewriting the field would leave nothing to compare a rewrite
against. Seven briefs stay untouched every month on purpose: they are the control.

**Risk is out of reach.** The chief may rewrite anything about how an advisor
thinks, including its whole strategy. It cannot loosen a position limit, because
limits are not in any brief — they are in `risk.py`, on the only path from an
opinion to the book, and a brief that instructs an advisor to exceed one simply
produces a month of refused orders. This is not a promise made in a prompt. It is
where the two things live.

The open question this leaves, deliberately unanswered: nothing stops the desk
converging. If the loop keeps rewriting whoever is last, eight strategies may drift
towards one, and a leaderboard of eight identical advisors measures nothing. The
`diversity` figure in each record is there so that drift is observed rather than
discovered late.
"""
import datetime as dt
import difflib
import json
import re
from pathlib import Path

WINDOW_DAYS = 28
MIN_ROWS = 10                 # a month with fewer valuations than this is not a month
SHRINK_FLOOR = 0.5            # a rewrite may not gut the brief
GROWTH_CEILING = 2.0          # nor bury it

STATE = "company/data/evolution.json"


def _read(root, rel, default=None):
    path = Path(root) / rel
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def due(root, date):
    """Is a rewrite owed today? At most one per calendar month."""
    state = _read(root, STATE, {}) or {}
    last = state.get("last_run", "")
    return last[:7] < date[:7]


def window_start(date):
    return (dt.date.fromisoformat(date) - dt.timedelta(days=WINDOW_DAYS)).isoformat()


def standings(root, advisors, date, ledger):
    """Trailing-window return for every advisor, worst first. None where too short."""
    since = window_start(date)
    rows = []
    for advisor in advisors:
        series = _read(root, f"company/data/nav/{advisor['id']}.json", {"series": []})
        inside = [r for r in series.get("series", []) if r.get("date", "") >= since]
        rows.append({"advisor": advisor["id"], "name": advisor["ad"],
                     "rows": len(inside),
                     "window_return_pct": ledger.window_return(series, since),
                     "overall": ledger.series_stats(series)})
    ranked = [r for r in rows if r["window_return_pct"] is not None
              and r["rows"] >= MIN_ROWS]
    ranked.sort(key=lambda r: r["window_return_pct"])
    return rows, (ranked[0] if ranked else None)


def evidence(root, advisor_id, date):
    """Every order this advisor placed inside the window, and everything refused."""
    since = window_start(date)
    placed, refused, notes = [], [], []
    folder = Path(root) / "company/data/orders"
    for path in sorted(folder.glob("*.json")):
        if path.stem < since or path.stem > date:
            continue
        record = (_read(root, path.relative_to(root).as_posix(), {}) or {}) \
            .get("advisors", {}).get(advisor_id)
        if not record:
            continue
        for order in record.get("orders", []):
            placed.append(f"  {path.stem}  {order['action']:<4} "
                          f"${order['amount_usd']:>10,.2f}  {order['instrument']:<8} "
                          f"— {order.get('reason', '')}")
        for bad in record.get("rejected", []):
            refused.append(f"  {path.stem}  {bad['why']}")
        if record.get("note"):
            notes.append(f"  {path.stem}  {record['note']}")
    return {"placed": placed, "refused": refused, "notes": notes}


def diversity(root, advisors):
    """How alike the briefs have become, 0 to 1. Watched, not enforced.

    A crude measure on purpose: the mean pairwise similarity of the briefs as text.
    It will not notice two differently-worded identical strategies, and it is not
    meant to — it is an early warning that the loop is collapsing the field, put
    where a reader will see it every month rather than in a note nobody opens.
    """
    texts = []
    for advisor in advisors:
        path = Path(root) / f"company/agents/prompts/{advisor['id']}.md"
        if path.exists():
            texts.append(path.read_text(encoding="utf-8"))
    pairs = [difflib.SequenceMatcher(None, a, b).ratio()
             for i, a in enumerate(texts) for b in texts[i + 1:]]
    return round(sum(pairs) / len(pairs), 3) if pairs else 0.0


# --------------------------------------------------------------------------

REFUSALS = (
    (re.compile(r"^\s*$"), "the rewrite is empty"),
    (re.compile(r"\A(?!#\s)"), "a brief starts with a '# ' heading; this one does not"),
)

LIMIT_TALK = re.compile(
    r"(ignore|override|exceed|bypass|disregard|work around)\s+(the\s+)?"
    r"(risk|position|concentration|cash|size)\s*(limit|rule|cap)", re.I)


def acceptable(new_text, old_text, person):
    """Return the reason a rewrite cannot be published, or None.

    The same lesson as next door, in a new place: the cheap thing you can check
    about a rewritten file is not whether it is *good*, it is whether it is still
    the kind of thing it replaced. A brief that came back as one encouraging
    sentence is not a strict brief, it is a deleted advisor.
    """
    text = (new_text or "").strip()
    for pattern, why in REFUSALS:
        if pattern.search(text):
            return why
    ratio = len(text) / max(1, len(old_text.strip()))
    if ratio < SHRINK_FLOOR:
        return (f"the rewrite is {ratio:.0%} of the brief it replaces; below "
                f"{SHRINK_FLOOR:.0%} that is a deletion, not a revision")
    if ratio > GROWTH_CEILING:
        return (f"the rewrite is {ratio:.0%} of the brief it replaces; above "
                f"{GROWTH_CEILING:.0%} nothing in it can be acted on daily")
    if person.split()[0].lower() not in text.lower():
        return (f"the rewrite never names {person}; a brief is one colleague's "
                "instructions, not a memo to the floor")
    if LIMIT_TALK.search(text):
        return ("the rewrite instructs the advisor to get around a risk limit. "
                "Limits are enforced in code the advisor never touches, so this "
                "would produce a month of refused orders and nothing else")
    return None


def diff(old_text, new_text, advisor_id):
    return "".join(difflib.unified_diff(
        old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
        fromfile=f"a/{advisor_id}.md", tofile=f"b/{advisor_id}.md"))
