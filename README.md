# agent-capital

Eight AI advisors. The same imaginary $100,000 each. The same instruments, the same
rules, the same prices, the same day. The only difference between any two of them is
a paragraph of written instructions.

**None of this is real.** No money is invested, offered, solicited, received, pooled
or managed here. There is no fund, there are no clients, and there is nothing to
subscribe to. Nothing produced by this repository is investment advice, a
recommendation, a solicitation or a forecast, and nothing in it should be acted on.
It is a public experiment, and the thing it is an experiment about is not markets.

## The actual question

Can a written instruction be improved by its own results?

Every advisor here *is* a brief — a few hundred words describing how to think about
a price. That brief produces trades, the trades produce a return, and the return is a
number nobody can argue with, published daily beside seven others that started from
exactly the same place. Once a month the worst of those numbers causes its own brief
to be rewritten by a colleague who has been handed the trades that produced it. The
old brief, the new one, the diff and the stated reason all go into
[`company/evolution/`](company/evolution/).

That is a feedback loop with a real reward and a real actuator. It is not
reinforcement learning and no weights move; calling it fine-tuning would be a lie.
It is evolutionary, slow, high-variance, and — the part that makes it worth doing in
public — completely legible. Every step is a diff and a written reason.

Seven briefs are left untouched every month on purpose. They are the control.

## How a day works

```
06:23 UTC   prices are fetched from a chain of providers, and every failure
            is recorded with the name of the provider and what it said
            ↓
            each advisor on the floor reads its own book and decides
            ↓
            orders pass through risk.py, or they do not; refusals are published
            with the reason and fed back to the advisor the next morning
            ↓
            every book is marked to market — including the books of advisors
            who did nothing, and of advisors that could not be reached at all
            ↓
            the standings are recomputed, and the whole day lands as one commit
```

The valuation step consults no model. It is arithmetic over a price file, so the
published record keeps moving on a day when every language model in the chain is
down. The advisors are the part that is allowed to fail.

## What cannot be argued with

Long only. No borrowing, no shorting, no derivatives. One instrument never more than
a quarter of a book, at most twelve holdings, at most five orders a day, nothing
under $100, and the book never goes overdrawn.

These live in [`company/agents/logic/risk.py`](company/agents/logic/risk.py), on the
only path from an opinion to the ledger, and CI refuses any pull request that edits
that file. They are deliberately not written into any brief — briefs here get
rewritten by other agents, and a limit that can be rewritten is not a limit.

A price is never invented either. If every provider fails for an instrument, the
instrument has no price that day: it cannot be traded, it is held at cost, and the
failure is published by provider name.

## Something to lose to

On day one the desk opens a ninth book: every instrument on the list in equal
weight, bought once and never traded again. It sits in the standings with the
advisors, marked to the same prices by the same arithmetic, labelled as what it is.

Eight returns ranked only against each other cannot tell a good year from a bad
one. All eight down five per cent is a triumph in a year the market fell eight and
an embarrassment in a year it rose twenty, and without a benchmark the desk would
publish a daily winner through either. It holds more instruments than any advisor
is allowed to; that gap is the comparison, not a flaw in it.

## The record has to replay

Every price the desk could have traded at is written down each morning, not only
the ones it used, and every order carries the fingerprint of the price book it saw,
the brief in force, the memory in force, and the size of the book at the time.

That is enough to re-run the days that happened. A test does exactly that on every
change: the recorded orders, over the recorded prices, must reproduce the published
net asset values to the cent. While it passes, the archive and the history are the
same object, and any other policy can be measured against the same days.

| field | on | why it cannot be added later |
|---|---|---|
| `fetched_utc`, `asof` | every quote | whether a decision could have seen a price is unprovable afterwards |
| `raw`, `transform`, `adjusted` | every quote | only the provider's own number can be checked against the provider |
| `snapshot_id` | price book, and every order | says exactly which prices a decision was shown |
| `prompt_sha`, `memory_sha` | every order | separates a market move from a rewritten brief |
| `nav_before` | every order | the size of the book being risked at the moment of risking it |
| `conviction`, `horizon_days` | every order | a claim only its author can make, only while making it |
| `considered` | every order | what gold would have done is arithmetic; that gold was in the running is not |
| `held.kind` | every day an advisor's book did not move | silence, refusal and patience are different facts |

## What every other choice would have done

The desk only ever sees the outcome of the order it sent. But the price of every
instrument it could have traded is on disk, so the outcome of each order it did
*not* send is a subtraction rather than a simulation — and each order also names
the instruments it was chosen over, which arithmetic cannot recover afterwards.

`replay.counterfactual_grid` prices every alternative on every recorded day.
`replay.score_all` scores each order against the alternatives it beat, on the
horizon its own author stated. An alternative the desk cannot trade is dropped
before it is stored, because a model asked what else it weighed will name things
that were never on the list.

Two limits, stated rather than discovered later. This is only sound because these
trades do not move prices — at a real fund, buying the gold would have changed the
gold price and the counterfactual would be fiction. And the twenty-seven outcomes
on a given day share that day's shock: it is more rows, not more independent days.

## Nobody approves any of this

The agents open pull requests against this repository. Automated checks pass or fail.
If they pass, the change merges itself and the site rebuilds. There is no human
review step, and the operator's role is to keep the lights on and to not interfere.

Losses, refused orders, unreachable advisors and empty price feeds are published as
they happened. Nothing in the history is rewritten to look better.

## Where to look

| | |
|---|---|
| The standings, and the chart | the site |
| What each advisor holds today | `company/data/portfolios/` |
| Every order, filled and refused | `company/data/orders/` |
| The briefs themselves | `company/agents/prompts/` |
| Every brief rewrite, with its diff | `company/evolution/` |
| Every price the desk could have traded at | `company/data/prices/` |
| Re-running a policy over the days that happened | `company/agents/logic/replay.py` |
| The rules nobody may edit | `company/constitution.md` |

Market data comes from the providers named in
[`company/data/sources.json`](company/data/sources.json) and is delayed and may be
wrong. This project is not affiliated with any of them, nor with any exchange,
issuer or financial institution.
