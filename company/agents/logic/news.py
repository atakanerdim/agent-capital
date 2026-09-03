"""Facts from outside, and the exact moment each one became public.

The desk has traded blind until now: prices and its own record, and the briefs say
so in as many words. That produces a boring result — an advisor reading only a
price list is being asked whether a language model can chart, which it cannot, and
the answer teaches nothing. What is worth asking is whether its stated reasoning
about a *fact* predicts anything, and that needs facts with timestamps.

Timestamps, not headlines. This module's whole difficulty is one asymmetry:

    A price that arrives late is a missing price. A fact that arrives early is
    invented skill.

A feed that lets you ask "what was the news on the 3rd" and answers on the 10th
will hand an advisor a week of hindsight, the returns will look extraordinary, and
nothing will announce the error — it shows up as talent. So every item here
carries `published_utc` taken from the provider's own record, an advisor is only
ever shown items published strictly before the instant it was asked, and an item
with no publication instant is collected and never shown. Not a convention: a
test, over the archive, on every change.

Three families, all public domain and redistributable, which is why they were
chosen over a commercial wire that could not legally be republished here.

**SEC EDGAR** carries a real acceptance instant and is the working part. That
instant is when the filing became publicly retrievable; a company's own press
release often precedes it, so the stamp is late rather than early relative to what
the market knew. Late is the safe direction — it weakens a real effect instead of
inventing one.

**FRED** is collected and never shown. The keyless CSV gives observations, not
release instants, and August's inflation figure is published in mid-September:
treating the observation date as the publication date would be a month of hindsight
on every macro item. It is still fetched daily, because FRED revises its history
and what a series said on a given day cannot be recovered from FRED afterwards.

**The FOMC calendar** is shown freely, because a schedule is not news. That the
committee meets on a given date has been public for a year. What happens at the
meeting is a different fact, and this family does not carry it.
"""
import csv
import datetime as _dt
import io
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 25
# The SEC asks that automated clients identify themselves and say how to be
# reached; an anonymous crawler is throttled and, per their fair-access notice,
# may be blocked outright.
USER_AGENT = ("agent-capital/1.0 (a public, non-commercial paper-trading "
              "experiment; +https://github.com/atakanerdim/agent-capital)")
MAX_PER_COMPANY = 3          # newest filings per company per day
MAX_SHOWN = 12               # items in one advisor's prompt


def now_utc():
    """The instant something happened, to the second, in UTC.

    Public because the desk stamps each decision with it, and the fence compares
    against that stamp. One clock for both sides of the comparison or the
    comparison means nothing.
    """
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


_now_utc = now_utc


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8", "replace")


def load_sources(root):
    path = Path(root) / "company/data/news_sources.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {family["family"]: family for family in doc["families"]}


def _iso_instant(value):
    """A provider's publication instant, normalised to UTC. None if unusable.

    EDGAR writes `2026-09-01T22:32:04.000Z`. Anything that will not parse is
    dropped rather than repaired: a timestamp this module is unsure about is worse
    than none, because the fence would let the item through on a guess.
    """
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        stamp = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_dt.timezone.utc)
    return stamp.astimezone(_dt.timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------
# One reader per family.
# --------------------------------------------------------------------------

def _edgar(family, fetched):
    """Recent filings for every company on the list, with their acceptance instant."""
    wanted = set(family.get("forms") or [])
    items, short = [], []
    for company in family.get("companies", []):
        cik = int(company["cik"])
        url = family["base"].format(cik=f"{cik:010d}")
        try:
            recent = (json.loads(_fetch(url)).get("filings") or {}).get("recent") or {}
        except (urllib.error.URLError, OSError, ValueError, KeyError,
                json.JSONDecodeError) as e:
            short.append({"family": "sec_edgar", "instrument": company["instrument"],
                          "why": f"{type(e).__name__}: {e}"[:180]})
            continue
        forms = recent.get("form") or []
        taken = 0
        for i, form in enumerate(forms):
            if wanted and form not in wanted:
                continue
            published = _iso_instant((recent.get("acceptanceDateTime") or [None] * (i + 1))[i])
            if not published:
                continue
            accession = (recent.get("accessionNumber") or [""] * (i + 1))[i]
            document = (recent.get("primaryDocument") or [""] * (i + 1))[i]
            described = (recent.get("primaryDocDescription") or [""] * (i + 1))[i]
            items.append({
                "id": f"edgar:{accession}",
                "source": "sec_edgar",
                "kind": form,
                "instrument": company["instrument"],
                "published_utc": published,
                "fetched_utc": fetched,
                "anticipated": False,
                "headline": f"{company['instrument']} filed a {form}"
                            + (f" — {described}" if described else ""),
                "value": None,
                "url": family["landing"].format(
                    cik_plain=cik, accession_nodash=accession.replace("-", ""),
                    document=document) if accession and document else None})
            taken += 1
            if taken >= MAX_PER_COMPANY:
                break
    return items, short


def _fred(family, fetched):
    """The latest observation of each series. Never shown; see the module docstring."""
    items, short = [], []
    for series in family.get("series", []):
        url = family["base"].format(series=series["id"])
        try:
            rows = [r for r in csv.reader(io.StringIO(_fetch(url).strip())) if r]
        except (urllib.error.URLError, OSError, ValueError) as e:
            short.append({"family": "fred", "instrument": None,
                          "why": f"{type(e).__name__}: {e}"[:180]})
            continue
        last = next((r for r in reversed(rows[1:])
                     if len(r) > 1 and r[1] not in ("", ".", "NA")), None)
        if not last:
            short.append({"family": "fred", "instrument": None,
                          "why": f"{series['id']} had no usable observation"})
            continue
        try:
            value = float(last[1])
        except ValueError:
            continue
        items.append({
            "id": f"fred:{series['id']}:{last[0]}",
            "source": "fred",
            "kind": series["id"],
            "instrument": None,
            # Deliberately null. The observation date is not the release date, and
            # the fence turns that null into "never shown" rather than a guess.
            "published_utc": None,
            "fetched_utc": fetched,
            "anticipated": False,
            "headline": f"{series['what']}: {value} as of {last[0]}",
            "value": value,
            "asof": last[0],
            "url": None})
    return items, short


def _calendar(family, fetched, today):
    """Scheduled meetings. Public a year ahead, so showing them is not hindsight."""
    items = []
    for meeting in family.get("meetings", []):
        if meeting["end"] < today:
            continue
        items.append({
            "id": f"fomc:{meeting['start']}",
            "source": "fomc_calendar",
            "kind": "fomc_meeting",
            "instrument": None,
            "published_utc": None,
            "fetched_utc": fetched,
            "anticipated": True,
            "headline": (f"FOMC meets {meeting['start']} to {meeting['end']}"
                         + (", with a Summary of Economic Projections"
                            if meeting.get("projections") else "")
                         + " (the Federal Reserve calls every date tentative until "
                           "the preceding meeting confirms it)"),
            "value": None,
            "asof": meeting["start"],
            "url": family.get("source_url")})
    return items, []


def _mock(root):
    path = Path(root) / "tests/mock_news.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def fetch(root, date):
    """Everything the desk could read today, whether or not anybody is shown it.

    Recorded the same way as the price book and for the same reason: the archive
    keeps the whole set, and marks separately which items reached an advisor. What
    was available but not shown is exactly what a later study needs.
    """
    fetched = _now_utc()
    if os.environ.get("MOCK_HTTP") == "1":
        items = [dict(item, fetched_utc=fetched) for item in _mock(root)]
        return {"date": date, "fetched_utc": fetched, "items": items, "short": []}
    sources = load_sources(root)
    items, short = [], []
    for name, reader in (("sec_edgar", _edgar), ("fred", _fred)):
        family = sources.get(name)
        if not family:
            continue
        got, failed = reader(family, fetched)
        items += got
        short += failed
    if sources.get("fomc_calendar"):
        got, _ = _calendar(sources["fomc_calendar"], fetched, date)
        items += got
    items.sort(key=lambda i: (i.get("published_utc") or "", i["id"]))
    return {"date": date, "fetched_utc": fetched, "items": items, "short": short}


# --------------------------------------------------------------------------
# The fence.
# --------------------------------------------------------------------------

def visible(items, decided_utc):
    """The items an advisor asked at `decided_utc` was allowed to know.

    Two ways through, and no third. Either the provider stamped the item with a
    publication instant and that instant is strictly earlier than the question, or
    the item is a schedule, which was public long before either. An item with no
    stamp and no schedule is not shown — not because it is untrue, but because
    nothing here can prove when it stopped being secret.

    Strictly earlier, not earlier-or-equal: a filing accepted in the same second
    the advisor was asked is a coin toss, and this fence does not toss coins.
    """
    if not decided_utc:
        return []
    out = []
    for item in items:
        if item.get("anticipated"):
            out.append(item)
            continue
        published = item.get("published_utc")
        if published and published < decided_utc:
            out.append(item)
    return out


def for_advisor(items, universe, limit=MAX_SHOWN):
    """The visible items worth spending an advisor's context on.

    Filings for instruments outside this desk's list are dropped: an advisor that
    cannot trade a company does not need to read about it, and every line here is
    paid for in tokens on every call. Newest first, because a filing from three
    weeks ago is not what today's decision turns on.
    """
    kept = [i for i in items
            if i.get("instrument") is None or i["instrument"] in universe]
    kept.sort(key=lambda i: (i.get("published_utc") or i.get("asof") or ""),
              reverse=True)
    return kept[:limit]


def audit(root):
    """Every look-ahead violation in the whole archive. Empty is the only passing answer.

    The sibling of the replay invariant, and the more important of the two. A
    replay that stops reproducing the ledger is a bookkeeping bug and looks like
    one. A news item shown before it was published does not look like a bug at all
    — it looks like an advisor with an edge, the numbers improve, and every
    conclusion drawn from the archive afterwards is quietly worthless.

    So the claim "no advisor was ever shown something it could not have known" is
    not left as a property of the code that writes the record. It is checked
    against the record itself, over every decision ever made, on every change.
    """
    news_dir = Path(root) / "company/news"
    orders_dir = Path(root) / "company/data/orders"
    published = {}
    for path in sorted(news_dir.glob("*.json")):
        try:
            day = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for item in day.get("items") or []:
            published[item["id"]] = item

    violations = []
    for path in sorted(orders_dir.glob("*.json")):
        try:
            day = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for advisor, record in (day.get("advisors") or {}).items():
            decided = record.get("decided_utc")
            for item_id in record.get("news_shown") or []:
                item = published.get(item_id)
                if item is None:
                    violations.append({
                        "date": day.get("date"), "advisor": advisor, "item": item_id,
                        "why": "shown an item that is in no day's news record"})
                    continue
                if item.get("anticipated"):
                    continue
                stamp = item.get("published_utc")
                if not stamp:
                    violations.append({
                        "date": day.get("date"), "advisor": advisor, "item": item_id,
                        "why": "shown an item with no publication instant"})
                elif not decided:
                    violations.append({
                        "date": day.get("date"), "advisor": advisor, "item": item_id,
                        "why": "shown news but the decision has no decided_utc"})
                elif stamp >= decided:
                    violations.append({
                        "date": day.get("date"), "advisor": advisor, "item": item_id,
                        "why": f"published {stamp}, decided {decided}"})
    return violations


def render(items):
    """The block an advisor reads. Facts and their instants, nothing editorial."""
    if not items:
        return "  (nothing had been published by the time you were asked)"
    lines = []
    for item in items:
        when = item.get("published_utc") or item.get("asof") or "?"
        lines.append(f"  [{when}] {item['headline']}")
    return "\n".join(lines)
