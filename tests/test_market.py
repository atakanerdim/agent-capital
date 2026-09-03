"""A price comes from a named provider or it does not exist.

The failure this guards against is not an outage. It is a symbol that has never
worked: an instrument quietly never priced, never traded and never noticed, while
the desk goes on looking healthy. Every symbol in universe.json was written from a
provider's documented convention and confirmed against nothing, which is why the
failure is recorded by provider name rather than counted.
"""
import json


def test_the_universe_and_the_sources_agree(company, logic):
    market = logic(company, "market")
    known = {s["source"] for s in market.load_sources(company).values()}
    for instrument in market.load_universe(company):
        assert instrument.get("quotes"), f"{instrument['id']} has no provider at all"
        for entry in instrument["quotes"]:
            assert entry["source"] in known, \
                f"{instrument['id']} names a provider that sources.json does not define"


def test_every_instrument_has_a_second_provider(company, logic):
    """One provider is a single point of failure with a leaderboard attached."""
    market = logic(company, "market")
    alone = [i["id"] for i in market.load_universe(company) if len(i["quotes"]) < 2]
    assert not alone, f"these can only be priced one way: {alone}"


def test_instrument_ids_are_unique(company, logic):
    market = logic(company, "market")
    ids = [i["id"] for i in market.load_universe(company)]
    assert len(ids) == len(set(ids))


def test_a_price_is_never_invented(company, logic):
    """Every provider fails: the instrument has no price and says who was asked."""
    market = logic(company, "market")
    sources = market.load_sources(company)
    instrument = {"id": "NOPE", "name": "Nothing", "class": "equity",
                  "quotes": [{"source": "stooq", "symbol": "definitely-not-a-symbol"}]}

    def explode(url):
        raise OSError("the network is not here")

    market._fetch = explode
    record, tried = market.quote(instrument, sources)
    assert record is None
    assert tried and tried[0]["source"] == "stooq" and "OSError" in tried[0]["why"]


def test_the_chain_falls_through_to_the_next_provider(company, logic):
    market = logic(company, "market")
    sources = market.load_sources(company)
    calls = []

    def flaky(url):
        calls.append(url)
        if "stooq" in url:
            raise OSError("down")
        return json.dumps({"amount": 1.0, "base": "USD", "date": "2026-09-04",
                           "rates": {"EUR": 0.8}})

    market._fetch = flaky
    instrument = {"id": "EURUSD", "name": "Euro", "class": "fx",
                  "quotes": [{"source": "stooq", "symbol": "eurusd"},
                             {"source": "frankfurter", "symbol": "EUR", "invert": True}]}
    record, tried = market.quote(instrument, sources)
    assert record["source"] == "frankfurter" and round(record["close"], 4) == 1.25
    assert len(calls) == 2 and tried[0]["source"] == "stooq"


def test_a_pair_quoted_the_other_way_up_is_inverted(company, logic):
    market = logic(company, "market")
    rate, _ = market._read_frankfurter(json.dumps({"rates": {"JPY": 150.0}}), "JPY")
    assert round(1 / rate, 6) == round(1 / 150.0, 6)


def test_a_stooq_row_is_read_from_its_header(company, logic):
    market = logic(company, "market")
    body = ("Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "AAPL.US,2026-09-04,22:00:07,230.1,233.4,229.8,231.5,41234567\n")
    assert market._read_stooq_csv(body) == (231.5, "2026-09-04")


# --------------------------------------------------------------------------
# What the record has to carry for the archive to still be readable in 2030.
# --------------------------------------------------------------------------

def test_a_quote_records_when_it_was_fetched_and_what_day_it_is_for(company, logic):
    """The look-ahead question is answered at fetch time or never.

    A price pulled at 06:23 UTC may belong to yesterday's close. If the record
    holds only the shift's date, nobody can tell afterwards, and every return
    computed from the series inherits the doubt.
    """
    market = logic(company, "market")
    sources = market.load_sources(company)
    market._fetch = lambda url: json.dumps(
        {"amount": 1.0, "base": "USD", "date": "2026-09-03", "rates": {"EUR": 0.8}})
    record, _ = market.quote(
        {"id": "EURUSD", "name": "Euro", "class": "fx",
         "quotes": [{"source": "frankfurter", "symbol": "EUR", "invert": True}]},
        sources)
    assert record["asof"] == "2026-09-03"          # the provider's own stated day
    assert record["fetched_utc"].endswith("+00:00")
    assert record["fetched_utc"][:4].isdigit()


def test_a_provider_that_states_no_date_gets_none_not_a_guess(company, logic):
    """Writing the shift's date here would be inventing a fact about the provider."""
    market = logic(company, "market")
    price, asof = market._read_yahoo_chart(json.dumps(
        {"chart": {"result": [{"meta": {"previousClose": 100.0}}]}}))
    assert price == 100.0 and asof is None


def test_a_malformed_provider_date_is_dropped_rather_than_stored(company, logic):
    market = logic(company, "market")
    body = ("Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "X.US,N/D,22:00:07,1,1,1,231.5,1\n")
    assert market._read_stooq_csv(body) == (231.5, None)


def test_the_raw_provider_number_survives_next_to_the_transformed_one(company, logic):
    """close is what the desk trades at; raw is what the provider actually said.

    Only raw can be checked against the provider years later. Keeping just the
    transformed number makes an inverted or mis-scaled pair indistinguishable from
    a real move.
    """
    market = logic(company, "market")
    sources = market.load_sources(company)
    market._fetch = lambda url: json.dumps(
        {"date": "2026-09-04", "rates": {"JPY": 150.0}})
    record, _ = market.quote(
        {"id": "JPYUSD", "name": "Yen", "class": "fx",
         "quotes": [{"source": "frankfurter", "symbol": "JPY", "invert": True}]},
        sources)
    assert record["raw"] == 150.0
    assert record["close"] == round(1 / 150.0, 6)
    assert record["transform"] == {"invert": True, "scale": 1.0}


def test_every_provider_declares_whether_its_history_is_restated(company, logic):
    """Not detectable from a response, so it is declared — and never left blank."""
    market = logic(company, "market")
    allowed = {"split_and_dividend", "none", "unknown"}
    for source in market.load_sources(company).values():
        assert source.get("adjusted") in allowed, \
            f"{source['source']} does not say whether its closes are restated"


def test_the_declared_adjustment_lands_on_the_quote(company, logic):
    market = logic(company, "market")
    sources = market.load_sources(company)
    market._fetch = lambda url: json.dumps(
        {"date": "2026-09-04", "rates": {"EUR": 0.8}})
    record, _ = market.quote(
        {"id": "EURUSD", "name": "Euro", "class": "fx",
         "quotes": [{"source": "frankfurter", "symbol": "EUR", "invert": True}]},
        sources)
    assert record["adjusted"] == sources["frankfurter"]["adjusted"]
    assert record["symbol"] == "EUR"


def test_the_snapshot_id_names_the_market_not_the_moment(company, logic):
    """Two runs of the same day must fingerprint the same, or an order record
    cannot point at what its advisor saw. Fetch times differ between an early
    shift and its afternoon retry; the prices are what the decision depended on."""
    market = logic(company, "market")
    morning = {"SPY": {"close": 662.4, "fetched_utc": "2026-09-04T06:23:00+00:00"},
               "AAPL": {"close": 231.5, "fetched_utc": "2026-09-04T06:23:01+00:00"}}
    afternoon = {"AAPL": {"close": 231.5, "fetched_utc": "2026-09-04T14:41:00+00:00"},
                 "SPY": {"close": 662.4, "fetched_utc": "2026-09-04T14:41:02+00:00"}}
    assert market.snapshot_id(morning) == market.snapshot_id(afternoon)
    moved = dict(afternoon, SPY={"close": 662.5, "fetched_utc": "x"})
    assert market.snapshot_id(moved) != market.snapshot_id(morning)


def test_the_price_book_carries_its_own_snapshot_id(company, logic, monkeypatch):
    market = logic(company, "market")
    market._fetch = lambda url: (_ for _ in ()).throw(
        AssertionError("a test reached for the network"))
    monkeypatch.setenv("MOCK_HTTP", "1")
    book = market.prices(company, "2026-09-04")
    assert book["snapshot_id"] == market.snapshot_id(book["quotes"])
    assert len(book["snapshot_id"]) == 12


def test_a_row_with_no_data_is_a_failure_not_a_zero(company, logic):
    market = logic(company, "market")
    body = "Symbol,Date,Time,Open,High,Low,Close,Volume\nX.US,N/D,N/D,N/D,N/D,N/D,N/D,0\n"
    try:
        market._read_stooq_csv(body)
    except ValueError:
        return
    raise AssertionError("N/D must not be read as a price")


def test_the_shifts_never_touch_the_network_in_a_test(company, logic, monkeypatch):
    market = logic(company, "market")

    def explode(url):
        raise AssertionError("a test reached for the network")

    market._fetch = explode
    monkeypatch.setenv("MOCK_HTTP", "1")
    book = market.prices(company, "2026-09-04")
    assert book["quotes"] and book["covered"].endswith("/27")
