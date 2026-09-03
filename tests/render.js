/* Does the site actually render, or does it merely parse?
 *
 * The desk this one was built beside went dark twice. Both times CI was green,
 * because CI was checking that the HTML balanced and never that the JavaScript
 * produced anything. The second time, four pages served an empty shell for five
 * days and no test could have known.
 *
 * So this is not a syntax check — `node --check` already does that. This loads
 * app.js against the real site/data that build.py just produced, with a DOM small
 * enough to be honest about what it is, and asserts that each page put actual
 * content into its containers. A page that throws, or that quietly writes nothing,
 * fails here.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const DATA = path.join(ROOT, "site/data");

const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); };

function makeElement(id) {
  return {
    id, _html: "", _text: "", hidden: false,
    set innerHTML(v) { this._html = String(v); },
    get innerHTML() { return this._html; },
    set outerHTML(v) { this._html = String(v); },
    get outerHTML() { return this._html; },
    set textContent(v) { this._text = String(v); },
    get textContent() { return this._text; },
  };
}

async function renderPage(ids) {
  const nodes = {};
  ids.forEach((id) => { nodes[id] = makeElement(id); });

  global.document = {
    _title: "agent-capital — test",
    getElementById: (id) => nodes[id] || null,
    get title() { return this._title; },
    set title(v) { this._title = v; },
  };
  global.window = { console };
  global.fetch = async (url) => {
    const rel = String(url).replace(/^data\//, "").split("?")[0];
    const file = path.join(DATA, rel);
    if (!fs.existsSync(file)) return { ok: false, status: 404 };
    const body = fs.readFileSync(file, "utf8");
    return {
      ok: true, status: 200,
      text: async () => body,
      json: async () => JSON.parse(body),
    };
  };
  delete require.cache[require.resolve(path.join(ROOT, "site/app.js"))];
  require(path.join(ROOT, "site/app.js"));
  // app.js boots from an async IIFE; give its awaits a chance to settle.
  for (let i = 0; i < 60; i++) await new Promise((r) => setImmediate(r));
  return nodes;
}

(async function () {
  // --- standings -------------------------------------------------------
  let n = await renderPage(["company-name", "standings", "as-of", "nav-chart",
                            "chart-note", "evolution", "sources"]);
  check(/<table/.test(n.standings.innerHTML), "standings: no table was rendered");
  check(/Tobias Lindgren|Grace Okonkwo/.test(n.standings.innerHTML),
        "standings: no advisor name in the table");
  check(/\$1[0-9]{2},/.test(n.standings.innerHTML),
        "standings: no book value that looks like money");
  check(/<svg/.test(n["nav-chart"].innerHTML), "standings: the NAV chart did not draw");
  check(/<path/.test(n["nav-chart"].innerHTML), "standings: the chart has no lines");
  check(/stooq|frankfurter/.test(n.sources.innerHTML),
        "standings: the providers panel is empty");
  // Before the chief has named it, name.txt is empty and the header keeps the
  // repository name. That is the correct state on day one, so this only asserts
  // the reading, not that a name exists.
  const chosen = fs.existsSync(path.join(DATA, "name.txt"))
    ? fs.readFileSync(path.join(DATA, "name.txt"), "utf8").trim() : "";
  check(chosen === "" || n["company-name"].textContent === chosen,
        "standings: name.txt says \"" + chosen + "\" and the header does not");

  // --- the book --------------------------------------------------------
  n = await renderPage(["company-name", "desk-date", "today", "books", "prices"]);
  check(/<div class="card"/.test(n.today.innerHTML), "book: today's cards are empty");
  check(/refused/.test(n.today.innerHTML),
        "book: a refused order should be visible — the fixture has one");
  check(/<table/.test(n.books.innerHTML), "book: no holdings table");
  check(/XAUUSD|SPY/.test(n.prices.innerHTML), "book: the price table is empty");

  // --- the floor -------------------------------------------------------
  n = await renderPage(["company-name", "today-line", "floor", "hallway-feed",
                        "minutes"]);
  check(/class="desk(?: on)?"/.test(n.floor.innerHTML), "floor: no desks were drawn");
  check(/Rafael Costa/.test(n.floor.innerHTML), "floor: operations is missing");
  // "desks" is the container and would be counted too; the desk itself is
  // class="desk" or class="desk on" and nothing else.
  check((n.floor.innerHTML.match(/class="desk(?: on)?"/g) || []).length === 11,
        "floor: all eleven colleagues should have a desk, got " +
        (n.floor.innerHTML.match(/class="desk(?: on)?"/g) || []).length);
  check(/class="bubble"/.test(n["hallway-feed"].innerHTML), "floor: the hallway is empty");
  check(/<details/.test(n.minutes.innerHTML), "floor: nothing filed under minutes");

  // --- changelog -------------------------------------------------------
  n = await renderPage(["company-name", "changelog"]);
  check(n.changelog.innerHTML.length > 0, "changelog: nothing rendered at all");

  if (failures.length) {
    failures.forEach((f) => console.error("RENDER FAILURE: " + f));
    process.exit(1);
  }
  console.log("render: every page produced content");
})();
