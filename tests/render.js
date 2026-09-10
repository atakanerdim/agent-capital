/* Does the site still have everything it needs to draw?
 *
 * The old version of this file stood up a hand-rolled fake DOM and let app.js
 * render into it. That stopped being possible when the pages were redesigned:
 * the new script uses <template> elements, cloneNode, replaceWith, classList and
 * createElementNS, and faking all of that faithfully means writing a browser —
 * at which point the test is mostly testing the fake.
 *
 * So this checks the seams instead, which is where the breakage actually happens.
 * A page goes blank for one of three reasons, and all three are caught here:
 *
 *   1. build.py stopped publishing a file, or a key inside it.
 *   2. an element id was renamed in the HTML but not in the script.
 *   3. a <template> the script clones is not on the page that uses it.
 *
 * None of those needs a DOM to detect, and all of them are silent in a browser:
 * the container simply stays empty and the page still returns 200.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SITE = path.join(ROOT, "site");
const DATA = path.join(SITE, "data");
const PAGES = ["index.html", "desk.html", "office.html", "changelog.html"];

const problems = [];
function check(ok, message) { if (!ok) { problems.push(message); } }

const app = fs.readFileSync(path.join(SITE, "app.js"), "utf8");
const html = {};
PAGES.forEach(function (p) { html[p] = fs.readFileSync(path.join(SITE, p), "utf8"); });
const allHtml = PAGES.map(function (p) { return html[p]; }).join("\n");

/* ---- 1. every file the script loads was actually published ---------------- */

const REQUIRED = {
  "view-standings.json": ["rows", "dates", "series", "holds", "record", "alloc", "instruments"],
  "view-today.json": ["entries"],
  "view-advisor.json": ["books"],
  "view-desk.json": ["advisors", "staff", "portraits"],
  "changelog.json": null
};

const loaded = [];
app.replace(/load\("data\/([^"]+)"/g, function (_, f) { loaded.push(f); return _; });
check(loaded.length > 0, "app.js loads no data at all");
loaded.forEach(function (file) {
  check(fs.existsSync(path.join(DATA, file)),
    "app.js loads data/" + file + " but build.py did not publish it");
});

Object.keys(REQUIRED).forEach(function (file) {
  const full = path.join(DATA, file);
  if (!fs.existsSync(full)) { problems.push("missing published file: " + file); return; }
  let doc;
  try { doc = JSON.parse(fs.readFileSync(full, "utf8")); }
  catch (e) { problems.push(file + " is not valid JSON: " + e.message); return; }
  const keys = REQUIRED[file];
  if (!keys) { return; }
  keys.forEach(function (k) {
    check(Object.prototype.hasOwnProperty.call(doc, k), file + " has no \"" + k + "\"");
  });
});

/* ---- 2. the views have something in them --------------------------------- */

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(path.join(DATA, file), "utf8")); }
  catch (e) { return null; }
}

const standings = readJson("view-standings.json");
if (standings) {
  check(Array.isArray(standings.rows) && standings.rows.length >= 2,
    "view-standings.json carries fewer than two books; the table would be empty");
  check(standings.rows.some(function (r) { return r.is_benchmark; }),
    "view-standings.json has no buy-and-hold row, so nothing is being compared against");
  check(Array.isArray(standings.dates) && standings.dates.length > 0,
    "view-standings.json has no dates, so the chart has no x axis");
  const keys = Object.keys(standings.series || {});
  check(keys.length > 0, "view-standings.json publishes no net asset value series");
  keys.forEach(function (k) {
    check((standings.series[k] || []).length === standings.dates.length,
      "series for " + k + " has " + (standings.series[k] || []).length +
      " points against " + standings.dates.length + " dates");
  });
}

const desk = readJson("view-desk.json");
if (desk) {
  check((desk.advisors || []).length > 0, "view-desk.json lists no advisors");
  (desk.advisors || []).forEach(function (p) {
    ["advisor", "name", "role", "mandate"].forEach(function (f) {
      check(p[f] !== undefined, "an advisor in view-desk.json has no " + f);
    });
  });
}

const books = (readJson("view-advisor.json") || {}).books || {};
check(Object.keys(books).length > 0, "view-advisor.json publishes no books");
Object.keys(books).forEach(function (k) {
  const b = books[k];
  ["name", "mandate", "nav", "cash", "invested", "return_pct",
   "max_drawdown_pct", "days", "positions", "record", "decisions"].forEach(function (f) {
    check(b[f] !== undefined, "book " + k + " has no " + f);
  });
});

/* ---- 3. every id and template the script reaches for exists in a page ----- */

const ids = new Set();
app.replace(/\$\("#([A-Za-z0-9_-]+)"/g, function (_, id) { ids.add(id); return _; });
app.replace(/getElementById\("([A-Za-z0-9_-]+)"\)/g, function (_, id) { ids.add(id); return _; });
ids.forEach(function (id) {
  check(allHtml.indexOf('id="' + id + '"') !== -1,
    'app.js reaches for #' + id + ' and no page defines it');
});

const templates = new Set();
app.replace(/(?:tpl|svgTpl)\("([A-Za-z0-9_-]+)"\)/g, function (_, id) { templates.add(id); return _; });
check(templates.size > 0, "app.js clones no templates, which cannot be right");
templates.forEach(function (id) {
  PAGES.forEach(function (p) {
    check(html[p].indexOf('<template id="' + id + '"') !== -1,
      p + " is missing <template id=\"" + id + "\">, which app.js clones");
  });
});

/* ---- 4. article 1 is on every page, in the markup, not the script -------- */

PAGES.forEach(function (p) {
  check(html[p].indexOf('class="badge fiction"') !== -1, p + " has lost the simulation badge");
  check(html[p].indexOf("No money is invested") !== -1, p + " has lost the no-money sentence");
  check(html[p].indexOf("produced autonomously by AI") !== -1, p + " has lost the AI disclosure");
});

if (problems.length) {
  problems.forEach(function (m) { console.error("ERROR: " + m); });
  process.exit(1);
}
console.log("site contract ok: " + PAGES.length + " pages, " + ids.size + " ids, " +
            templates.size + " templates, " + Object.keys(books).length + " books");
