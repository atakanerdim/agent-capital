"""Which price providers are actually answering — IMMUTABLE KERNEL (art. 2).

The language-model chain next door has a health check because models get retired
quietly and a chain can die link by link without anybody noticing until the whole
thing is dead. Price providers fail the same way and one worse way: a symbol can be
subtly wrong. `aapl.us` and `AAPL.US` and `aapl` are not all the same string to
every provider, and a symbol that has never worked looks exactly like a symbol that
has stopped working — an instrument that is quietly never priced, never traded, and
never noticed, because the desk goes on running perfectly without it.

Every symbol in `universe.json` was written from its provider's documented
convention and none of them has been confirmed against a live response. This is how
that gets confirmed: once a week, ask every provider for every instrument it claims
to cover, and write down what came back. It reports; it does not repair. A symbol
is a decision about what the desk trades, and repairing one automatically would
mean the desk could silently start pricing something other than what it says.
"""
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path


def _market(root):
    spec = importlib.util.spec_from_file_location(
        "logic_market", Path(root) / "company/agents/logic/market.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    root = Path.cwd()
    market = _market(root)
    sources = market.load_sources(root)
    universe = market.load_universe(root)
    date = dt.date.today().isoformat()

    lines = [f"[{date}] price provider health"]
    per_source = {name: {"ok": 0, "failed": 0} for name in sources}
    dead = []
    for instrument in universe:
        answers = []
        for entry in instrument.get("quotes", []):
            single = dict(instrument, quotes=[entry])
            record, tried = market.quote(single, sources)
            price = record["close"] if record else None
            name = entry.get("source", "?")
            if price is not None:
                per_source.setdefault(name, {"ok": 0, "failed": 0})["ok"] += 1
                answers.append(f"{name}=ok {price}")
            else:
                per_source.setdefault(name, {"ok": 0, "failed": 0})["failed"] += 1
                why = tried[0]["why"] if tried else "no answer"
                answers.append(f"{name}=FAILED ({why})")
        if all("FAILED" in a for a in answers):
            dead.append(instrument["id"])
        lines.append(f"  {instrument['id']:<8} " + " | ".join(answers))

    lines.append("")
    for name, tally in sorted(per_source.items()):
        lines.append(f"  {name}: {tally['ok']} ok, {tally['failed']} failed")
    if dead:
        lines.append("")
        lines.append("  NO PROVIDER COULD PRICE THESE AT ALL, so the desk cannot "
                     "trade them and has not been able to: " + ", ".join(dead))
        lines.append("  A wrong symbol looks exactly like this. Check universe.json "
                     "against the provider's own documentation before assuming an outage.")

    report = "\n".join(lines) + "\n"
    out = root / "company/log" / f"{date}-data.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
