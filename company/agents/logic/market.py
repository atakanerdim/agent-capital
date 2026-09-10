"""Where a price comes from, and what happens when it does not come.

The desk that this one was built beside gets its data from one provider on one
free key, and the day that provider is unhappy the whole week is missing. That is
survivable when the subject is football, because a fixture list keeps until
tomorrow. It is not survivable here: a price that never arrives is a portfolio
that cannot be valued, and a leaderboard that cannot be valued is a dead page.

So a price is not fetched from a provider. It is fetched from a *chain*, exactly
the way a language model is: `company/data/sources.json` lists the providers and
how to read each one, `universe.json` says which of them can quote a given
instrument and under what symbol, and this module walks that list until one of
them answers. Both files are data. Adding a provider is an edit to a JSON file,
not to code, and certainly not to the kernel.

Two things this module refuses to do.

It does not invent a price. If every link fails for an instrument, the instrument
has no price today and everything downstream is told so — the ledger holds the
position at cost, risk refuses to trade it, and the site says the feed was short.
A made-up number would be indistinguishable from a real one three weeks later.

It does not go to the network in a test. `MOCK_HTTP=1` serves the fixture, the
same switch the shifts already use, so CI is deterministic and offline.
"""
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 20
USER_AGENT = "agent-capital/1.0 (a public, non-commercial paper-trading experiment)"


def _now_utc():
    """The moment a quote was fetched, to the second, in UTC.

    This is recorded on every quote and it is not decoration. The shift runs at
    06:23 UTC; an American close fetched at that hour belongs to the *previous*
    trading day. Without a fetch time and a provider-stated date sitting next to
    each other in the record, nobody can prove months later whether a decision
    used a price it could not have seen. That question cannot be reconstructed
    afterwards, so it is answered at the moment the price arrives or never.
    """
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _iso_date(value):
    """A provider's own stated date, or None. Never a guess."""
    text = str(value or "").strip()[:10]
    try:
        _dt.date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8", "replace")


# --------------------------------------------------------------------------
# One reader per provider shape. Each returns a float, or raises.
# --------------------------------------------------------------------------

def _read_stooq_csv(body):
    rows = list(csv.DictReader(io.StringIO(body.strip())))
    if not rows:
        raise ValueError("empty csv")
    close = rows[0].get("Close") or rows[0].get("close")
    if close in (None, "", "N/D"):
        raise ValueError("no close in the row")
    return float(close), _iso_date(rows[0].get("Date") or rows[0].get("date"))


def _read_frankfurter(body, symbol):
    doc = json.loads(body)
    rates = doc.get("rates") or {}
    if symbol not in rates:
        raise ValueError(f"{symbol} not in the rates object")
    return float(rates[symbol]), _iso_date(doc.get("date"))


def _read_yahoo_chart(body):
    meta = json.loads(body)["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    # Only the regular market price carries a time we may trust. When we fall back
    # to the previous close, the stamp on the response belongs to a different bar
    # than the number we are taking, so the date is unknown and is written as such.
    asof = None
    if price:
        stamp = meta.get("regularMarketTime")
        if isinstance(stamp, (int, float)):
            asof = _dt.datetime.fromtimestamp(
                stamp, _dt.timezone.utc).date().isoformat()
    else:
        price = meta.get("previousClose")
    if not price:
        raise ValueError("no price in meta")
    return float(price), asof


def _yahoo_distributions(body):
    """The dividends Yahoo reports alongside the chart, as [{ex_date, amount}].

    Yahoo stamps each event at the market open of its ex-date (13:30 UTC), so the
    UTC calendar date is the ex-date. Only returned when the request asked for
    `events=div`; an empty list means the provider reported none in the window.
    """
    result = json.loads(body)["chart"]["result"][0]
    events = ((result.get("events") or {}).get("dividends") or {}).values()
    out = []
    for event in events:
        stamp, amount = event.get("date"), event.get("amount")
        if not isinstance(stamp, (int, float)) or not isinstance(amount, (int, float)):
            continue
        if amount <= 0:
            continue
        out.append({"ex_date": _dt.datetime.fromtimestamp(
            stamp, _dt.timezone.utc).date().isoformat(), "amount": float(amount)})
    return sorted(out, key=lambda e: e["ex_date"])


def _read_fred_csv(body):
    """FRED's keyless CSV: the last row that carries a value, and its date."""
    rows = [r for r in csv.reader(io.StringIO(body.strip())) if r]
    last = next((r for r in reversed(rows[1:])
                 if len(r) > 1 and r[1] not in ("", ".", "NA")), None)
    if not last:
        raise ValueError("no usable observation")
    return float(last[1]), _iso_date(last[0])


def _read_erapi(body, symbol):
    """exchangerate-api's open endpoint: rates against USD, with its own stamp."""
    doc = json.loads(body)
    rates = doc.get("rates") or {}
    if symbol not in rates:
        raise ValueError(f"{symbol} not in the rates object")
    stamp = doc.get("time_last_update_unix")
    asof = None
    if isinstance(stamp, (int, float)):
        asof = _dt.datetime.fromtimestamp(stamp, _dt.timezone.utc).date().isoformat()
    return float(rates[symbol]), asof


def _read(style, body, symbol):
    """Returns (price, provider_asof). The second may be None; it is never guessed."""
    if style == "stooq_csv":
        return _read_stooq_csv(body)
    if style == "frankfurter_json":
        return _read_frankfurter(body, symbol)
    if style == "yahoo_chart":
        return _read_yahoo_chart(body)
    if style == "erapi_json":
        return _read_erapi(body, symbol)
    if style == "fred_csv":
        return _read_fred_csv(body)
    raise ValueError(f"unknown source style {style!r}")


# --------------------------------------------------------------------------

def load_sources(root):
    doc = json.loads((Path(root) / "company/data/sources.json").read_text(encoding="utf-8"))
    return {s["source"]: s for s in doc["chain"]}


def load_universe(root):
    doc = json.loads((Path(root) / "company/data/universe.json").read_text(encoding="utf-8"))
    return doc["instruments"]


def _mock(root):
    path = Path(root) / "tests/mock_prices.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def quote(instrument, sources, mocked=None, allow_zero=False):
    """One instrument's price, and everything needed to audit it later.

    Returns (record, tried), where `record` is None when no link answered and
    `tried` records what each failing link said — that list is what the data desk
    publishes when a feed goes short, so it is written to be read rather than
    counted.

    The record keeps `raw` (the number the provider actually returned) beside
    `close` (the number after inverting and scaling), because three years from now
    the only way to check a price is against what the provider said, not against
    what this code made of it. `adjusted` is not detected — no provider announces
    it in a response — it is declared per provider in sources.json, and a provider
    that has not been checked says "unknown" rather than something reassuring.
    """
    tried = []
    if mocked is not None:
        if instrument["id"] in mocked:
            entry = mocked[instrument["id"]]
            value = float(entry["close"] if isinstance(entry, dict) else entry)
            record = {"close": value, "source": "mock", "symbol": None,
                      "raw": value, "transform": {"invert": False, "scale": 1.0},
                      "asof": None, "fetched_utc": _now_utc(),
                      "adjusted": "unknown"}
            if isinstance(entry, dict) and entry.get("distributions"):
                record["distributions"] = list(entry["distributions"])
            return record, tried
        return None, [{"source": "mock", "why": "not in the fixture"}]
    for entry in instrument.get("quotes", []):
        source = sources.get(entry.get("source"))
        if not source:
            tried.append({"source": entry.get("source"),
                          "why": "no such provider in sources.json"})
            continue
        try:
            fetched = _now_utc()
            body = _fetch(source["url"].format(symbol=entry["symbol"]))
            raw, asof = _read(source["style"], body, entry["symbol"])
            price = raw
            invert = bool(entry.get("invert"))
            scale = float(entry.get("scale", 1))
            if invert:
                if price == 0:
                    raise ValueError("a rate of zero cannot be inverted")
                price = 1.0 / price
            price *= scale
            if price < 0 or (price == 0 and not allow_zero):
                raise ValueError(f"a price of {price} is not a price")
            record = {"close": round(price, 6), "source": source["source"],
                      "symbol": entry["symbol"], "raw": raw,
                      "transform": {"invert": invert, "scale": scale},
                      "asof": asof, "fetched_utc": fetched,
                      "adjusted": source.get("adjusted", "unknown")}
            if source["style"] == "yahoo_chart" and "events=div" in source["url"]:
                paid = _yahoo_distributions(body)
                if paid:
                    record["distributions"] = paid
            return record, tried
        except (urllib.error.URLError, OSError, ValueError, KeyError,
                IndexError, TypeError, json.JSONDecodeError) as e:
            tried.append({"source": source["source"],
                          "why": f"{type(e).__name__}: {e}"[:180]})
    return None, tried


def snapshot_id(quotes):
    """A fingerprint of the price book a decision was shown.

    Computed over instrument ids and closes only — deliberately not over the fetch
    times, so that the same market state fingerprints the same way whether the
    shift ran once or was retried in the afternoon. This is the id an order record
    points at to say, without ambiguity, what the advisor was looking at.
    """
    canonical = json.dumps({k: v["close"] for k, v in sorted(quotes.items())},
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def load_rates(root):
    doc = json.loads((Path(root) / "company/data/universe.json").read_text(encoding="utf-8"))
    return doc.get("rates") or []


def prices(root, date):
    """Today's price for every instrument the desk is allowed to touch.

    Also the rates the ledger needs and nobody can trade: the overnight rate a
    book's cash earns is quoted the same way a price is, recorded in the same file,
    and missing the same way — named, with what every provider said.
    """
    sources = load_sources(root)
    universe = load_universe(root)
    mocked = _mock(root) if os.environ.get("MOCK_HTTP") == "1" else None
    out, short = {}, []
    for instrument in universe:
        record, tried = quote(instrument, sources, mocked)
        if record is None:
            short.append({"instrument": instrument["id"], "tried": tried})
            continue
        out[instrument["id"]] = dict(record, name=instrument["name"],
                                     **{"class": instrument["class"]})
    rates, rates_short = {}, []
    for rate in load_rates(root):
        record, tried = quote(rate, sources, mocked, allow_zero=True)
        if record is None:
            rates_short.append({"rate": rate["id"], "tried": tried})
            continue
        record.pop("distributions", None)
        rates[rate["id"]] = dict(record, pct=record["close"], name=rate["name"])
    book = {"date": date, "quotes": out, "short": short,
            "covered": f"{len(out)}/{len(universe)}",
            "snapshot_id": snapshot_id(out)}
    if rates or rates_short:
        book["rates"] = rates
        book["rates_short"] = rates_short
    return book
