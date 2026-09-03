"""The rules an advisor cannot argue with.

Every other thing about an advisor is soft. Their brief is a prompt, and once a
month the worst performer's prompt gets rewritten by a colleague who has just
read their losses — so a strategy here is a thing that can be talked out of
existence. That is the point of the experiment.

These are not that. A limit written into a prompt is a request; a limit written
here is a fact, because the only path from an advisor's opinion to the ledger
runs through `screen()`. An advisor may ask for anything. What reaches the book
is what survives this file.

The separation is deliberate and it is the whole safety story of the desk. If the
monthly rewrite could reach position sizing, one bad month of feedback could
produce an advisor who puts the entire book into one instrument, and the fence
that was supposed to stop it would be a sentence in the same file that just got
rewritten. So the fence does not live in a file anybody is allowed to rewrite.

The numbers themselves are not sacred and are meant to be argued about by a human
who is awake. What is sacred is where they live.
"""
import copy

# No leverage: an advisor spends money it has, and never more.
# No shorting: an advisor cannot lose more than it put in.
# No derivatives: nothing here has a payoff that is not the price.
MIN_ORDER_USD = 100.0        # below this it is noise, not a position
MAX_WEIGHT = 0.25            # one instrument, at most a quarter of the book
MAX_POSITIONS = 12           # a portfolio a reader can hold in their head
MAX_ORDERS_PER_DAY = 5       # an advisor is not a day-trading bot
CASH_FLOOR = 0.0             # the book never goes overdrawn

ACTIONS = ("buy", "sell")


class Rejected(ValueError):
    """An order that will not reach the book, and the sentence explaining why."""


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Rejected(f"{field} must be a number, got {value!r}")
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        raise Rejected(f"{field} must be a real number, got {value!r}")
    return value


# --------------------------------------------------------------------------
# Two fields risk records and never judges.
#
# `conviction` and `horizon_days` are what the advisor claims about its own order:
# how sure, and over what period it expects to be proved right. They exist so that
# the archive can later be asked whether stated confidence tracks realised outcome
# — which is the one question about a language model's market judgement that cannot
# be answered by re-reading its text, and cannot be reconstructed after the fact.
#
# They never accept or reject anything. An order is a good order or a bad one on
# its arithmetic; letting a model's own confidence move a limit would be handing it
# the key to the limit. And a missing or malformed value is recorded as absent
# rather than refused, because a schema newly introduced must not be the reason a
# desk stops trading in its first month. The gaps are counted where they happen.
# --------------------------------------------------------------------------

def conviction_of(order):
    """A number in [0, 1], or None. Never coerced into the middle."""
    value = order.get("conviction")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or not 0.0 <= value <= 1.0:
        return None
    return round(value, 3)


def horizon_of(order):
    """Whole days the advisor expects to wait, or None. Must be positive and sane."""
    value = order.get("horizon_days")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or not 1 <= value <= 3650:
        return None
    return int(value)


MAX_CONSIDERED = 5


def considered_of(order, universe):
    """The instruments this order was chosen *over*, cleaned. A claim, not an observation.

    The desk records the whole price book every day, so what gold would have done
    instead of silver is arithmetic. What arithmetic can never recover is that gold
    was ever in the running — and a decision plus the alternatives it beat is a
    labelled comparison, which is a far stronger thing to learn from than a
    decision alone. It exists only if it is written down at the moment of choosing.

    Two cautions are built in rather than hoped for. An instrument the desk cannot
    trade is dropped: a model asked what else it considered will happily name
    something that was never on the list, and an unfiltered field would quietly
    fill with inventions. The chosen instrument is dropped from its own
    alternatives, which models do offer.

    What remains is still only what the advisor *says* it weighed. Nothing here can
    confirm the alternative was genuinely considered rather than composed
    afterwards — which is not a reason to discard the field but a reason to label
    it, and it is why the archive stores it beside the outcome rather than as one.
    """
    raw = order.get("considered")
    if not isinstance(raw, list):
        return []
    chosen = str(order.get("instrument", "")).strip().upper()
    out, seen = [], set()
    for item in raw[:MAX_CONSIDERED * 3]:
        if isinstance(item, str):
            item = {"instrument": item}
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("instrument", "")).strip().upper()
        if symbol not in universe or symbol == chosen or symbol in seen:
            continue
        seen.add(symbol)
        out.append({"instrument": symbol,
                    "why_not": str(item.get("why_not", "")).strip()[:300]})
        if len(out) >= MAX_CONSIDERED:
            break
    return out


def check_one(order, portfolio, prices, universe, nav, orders_so_far):
    """Return a clean order, or raise Rejected with the reason.

    The reason is not for a log nobody reads. It goes back to the advisor in
    tomorrow's context, so it is written as a sentence a reader can act on.
    """
    if orders_so_far >= MAX_ORDERS_PER_DAY:
        raise Rejected(f"you have already placed {MAX_ORDERS_PER_DAY} orders today, "
                       "which is the limit; the rest of your ideas keep until tomorrow")

    action = str(order.get("action", "")).lower().strip()
    if action not in ACTIONS:
        raise Rejected(f"action must be one of {', '.join(ACTIONS)}, not {action!r}")

    instrument = str(order.get("instrument", "")).strip().upper()
    if instrument not in universe:
        raise Rejected(f"{instrument or '(blank)'} is not on the desk's instrument "
                       "list, and the desk does not trade what it cannot price")

    price = prices.get(instrument, {}).get("close")
    if not price or price <= 0:
        raise Rejected(f"there is no price for {instrument} today, so it cannot be "
                       "traded today; the data desk logs why")
    price = float(price)

    amount = _number(order.get("amount_usd", 0), "amount_usd")
    if amount < MIN_ORDER_USD:
        raise Rejected(f"an order of ${amount:,.2f} is below the ${MIN_ORDER_USD:,.0f} "
                       "minimum — too small to be a position, only a fee")

    held = portfolio["positions"].get(instrument, {"qty": 0.0, "cost": 0.0})

    if action == "buy":
        if amount > portfolio["cash"] - CASH_FLOOR:
            raise Rejected(f"you asked to spend ${amount:,.2f} and hold "
                           f"${portfolio['cash']:,.2f}; the desk does not borrow")
        after = (held["qty"] * price) + amount
        if nav > 0 and after > MAX_WEIGHT * nav:
            raise Rejected(
                f"{instrument} would become {after / nav:.0%} of your book and the "
                f"limit is {MAX_WEIGHT:.0%}; concentration is the one risk you are "
                "not allowed to take here")
        if held["qty"] == 0 and len(portfolio["positions"]) >= MAX_POSITIONS:
            raise Rejected(f"you already hold {MAX_POSITIONS} instruments, which is "
                           "the limit; sell something before buying something new")
        qty = amount / price
    else:
        if held["qty"] <= 0:
            raise Rejected(f"you do not hold {instrument}, and this desk does not "
                           "sell what it does not own")
        value = held["qty"] * price
        if amount > value + 0.01:
            amount = value           # selling "everything" is a normal thing to mean
        qty = amount / price

    return {"action": action, "instrument": instrument, "qty": qty, "price": price,
            "amount_usd": round(amount, 2),
            "reason": str(order.get("reason", "")).strip()[:400],
            "conviction": conviction_of(order),
            "horizon_days": horizon_of(order),
            "considered": considered_of(order, universe)}


def apply_order(portfolio, order):
    """Move one accepted order through a portfolio. The only arithmetic there is.

    It lives here rather than in the ledger because screening has to use it too.
    A day's orders are screened one after another against the book as it will
    actually stand when that order arrives — not against the book as it stood at
    breakfast. Screened the second way, five separate orders for a quarter of the
    book each would every one of them look like a quarter of the book, and an
    advisor would end a morning fully invested in five instruments with no cash
    and every single limit reporting that it had held.
    """
    held = portfolio["positions"].setdefault(order["instrument"],
                                             {"qty": 0.0, "cost": 0.0})
    if order["action"] == "buy":
        portfolio["cash"] -= order["amount_usd"]
        held["qty"] += order["qty"]
        held["cost"] += order["amount_usd"]
    else:
        share = min(1.0, order["qty"] / held["qty"]) if held["qty"] else 1.0
        portfolio["cash"] += order["amount_usd"]
        held["cost"] -= held["cost"] * share
        held["qty"] -= order["qty"]
    if held["qty"] <= 1e-9:
        portfolio["positions"].pop(order["instrument"], None)
    portfolio["cash"] = round(portfolio["cash"], 6)
    return portfolio


def screen(orders, portfolio, prices, universe, nav):
    """Split a day's requests into what reaches the book and what does not.

    `portfolio` is not modified. Each order is checked against a running copy that
    already carries the orders accepted before it, so the limits describe the book
    the advisor will actually end the day holding.
    """
    accepted, rejected = [], []
    if not isinstance(orders, list):
        return accepted, [{"order": repr(orders)[:200],
                           "why": "the orders field must be a list of orders"}]
    running = copy.deepcopy(portfolio)
    for raw in orders[: MAX_ORDERS_PER_DAY * 3]:
        if not isinstance(raw, dict):
            rejected.append({"order": repr(raw)[:200],
                             "why": "each order must be an object"})
            continue
        try:
            clean = check_one(raw, running, prices, universe, nav, len(accepted))
        except Rejected as why:
            rejected.append({"order": {k: raw.get(k) for k in
                                       ("action", "instrument", "amount_usd")},
                             "why": str(why)})
            continue
        apply_order(running, clean)
        accepted.append(clean)
    return accepted, rejected
