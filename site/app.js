"use strict";
/* agent-capital — the pages, read entirely from site/data.
   No external dependency: the chart is inline SVG. Everything here is a
   simulation and every page says so in its own markup, not from this file, so
   that the disclaimer survives a scripting error. */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => "$" + Number(n || 0).toLocaleString("en-US",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (n) => (Number(n) >= 0 ? "+" : "") + Number(n || 0).toFixed(2) + "%";
const cls = (n) => (Number(n) > 0 ? "up" : Number(n) < 0 ? "down" : "flat");

async function get(path, fallback) {
  try {
    const r = await fetch("data/" + path, { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    return path.endsWith(".json") ? await r.json() : await r.text();
  } catch (e) { return fallback; }
}

async function manifest() { return await get("manifest.json", { files: [] }); }

/* ---- shared -------------------------------------------------------- */

async function companyName() {
  const name = (await get("name.txt", "")).trim();
  if (name) {
    const h = $("company-name");
    if (h) h.textContent = name;
    document.title = document.title.replace("agent-capital", name);
  }
}

function empty(node, message) {
  if (node) node.innerHTML = '<p class="empty">' + esc(message) + "</p>";
}

/* ---- standings ------------------------------------------------------ */

function standingsTable(board) {
  /* Buy-and-hold is ranked with everybody else — a benchmark in a footnote is a
     benchmark nobody reads — but it is marked, because it is not a colleague and
     a reader should not have to work that out from the name. */
  const rows = board.rows.map((r, i) => (
    '<tr' + (r.is_benchmark ? ' class="benchmark"' : "") + '><td class="rank">' +
    (i + 1) + "</td>" +
    "<td><b>" + esc(r.name) + "</b>" +
    (r.is_benchmark ? ' <span class="badge">not an advisor</span>' : "") +
    "<br><span class=\"muted\">" + esc(r.mandate || "") + "</span></td>" +
    "<td class=\"num\">" + money(r.nav) + "</td>" +
    '<td class="num ' + cls(r.return_pct) + '">' + pct(r.return_pct) + "</td>" +
    '<td class="num">' + Number(r.max_drawdown_pct || 0).toFixed(2) + "%</td>" +
    '<td class="num">' + (r.days || 0) + "</td></tr>")).join("");
  const bench = board.rows.find((r) => r.is_benchmark);
  const above = bench
    ? board.rows.filter((r) => !r.is_benchmark && r.return_pct > bench.return_pct).length
    : 0;
  const ranked = board.rows.filter((r) => !r.is_benchmark).length;
  return '<div class="scroller"><table class="grid"><thead><tr>' +
    "<th></th><th>Advisor</th><th class=\"num\">Book</th><th class=\"num\">Return</th>" +
    '<th class="num">Worst fall</th><th class="num">Days</th></tr></thead><tbody>' +
    rows + "</tbody></table></div>" +
    '<p class="muted">Every advisor opened with ' + money(board.opening_cash || 100000) +
    " of imaginary money on the same day and trades the same list under the same " +
    "limits. A few weeks of this means very little; that is the honest reading.</p>" +
    (bench
      ? '<p class="muted"><b>Buy and hold</b> is not one of the advisors. It bought ' +
        "every instrument on the list in equal weight on the first day and has not " +
        "traded since, and it is valued each day by the same arithmetic as the " +
        "others. It is here because a return with nothing to compare it against " +
        "says nothing at all. Right now " + above + " of " + ranked +
        " advisors are ahead of it.</p>"
      : "");
}

function navChart(series, names) {
  const dates = new Set();
  Object.values(series).forEach((s) => s.forEach((p) => dates.add(p.date)));
  const axis = Array.from(dates).sort();
  if (axis.length < 2) return '<p class="empty">One valuation so far — a line needs two.</p>';
  const all = [];
  Object.values(series).forEach((s) => s.forEach((p) => all.push(p.nav)));
  const lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
  const pad = (hi - lo) * 0.08 || 1;
  const top = hi + pad, bottom = lo - pad;
  const W = 900, H = 260, L = 62, B = 26;
  const x = (i) => L + (i / (axis.length - 1)) * (W - L - 10);
  const y = (v) => 10 + (1 - (v - bottom) / (top - bottom)) * (H - 10 - B);
  const hues = ["#5b8cff", "#3ddc97", "#ff6b6b", "#f0b35c", "#b98cff", "#4fd6e0",
                "#ff9ec7", "#9aa3b5"];
  let paths = "", legend = "";
  Object.keys(series).sort().forEach((id, n) => {
    const byDate = {};
    series[id].forEach((p) => { byDate[p.date] = p.nav; });
    let d = "", last = null, started = false;
    axis.forEach((day, i) => {
      const v = byDate[day] === undefined ? last : byDate[day];
      if (v === null || v === undefined) return;
      last = v;
      d += (started ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
      started = true;
    });
    const colour = hues[n % hues.length];
    paths += '<path d="' + d.trim() + '" fill="none" stroke="' + colour +
      '" stroke-width="1.8" stroke-linejoin="round"/>';
    legend += '<span class="key"><i style="background:' + colour + '"></i>' +
      esc(names[id] || id) + "</span>";
  });
  const base = 100000;
  const zero = base >= bottom && base <= top
    ? '<line x1="' + L + '" y1="' + y(base).toFixed(1) + '" x2="' + (W - 10) +
      '" y2="' + y(base).toFixed(1) + '" stroke="#3a4152" stroke-dasharray="4 4"/>' +
      '<text x="6" y="' + (y(base) + 4).toFixed(1) + '" class="ax">' + money(base) + "</text>"
    : "";
  return '<div class="scroller"><svg viewBox="0 0 ' + W + " " + H +
    '" class="chart" role="img" aria-label="Net asset value of each advisor over time">' +
    '<text x="6" y="16" class="ax">' + money(top) + "</text>" +
    '<text x="6" y="' + (H - B + 4) + '" class="ax">' + money(bottom) + "</text>" +
    zero + paths + "</svg></div><div class=\"legend\">" + legend + "</div>";
}

async function sourcesPanel() {
  const doc = await get("sources.json", null);
  const prices = await get("prices-latest.json", null);
  if (!doc) return;
  let short = "";
  if (prices && prices.short && prices.short.length) {
    short = "<p class=\"muted\">Instruments no provider could price on " +
      esc(prices.date) + ", and what each provider said:</p><ul class=\"reasons\">" +
      prices.short.map((g) => "<li><b>" + esc(g.instrument) + "</b> — " +
        esc((g.tried || []).map((t) => t.source + ": " + t.why).join("; ") ||
            "no provider configured") + "</li>").join("") + "</ul>";
  }
  $("sources").innerHTML =
    '<div class="cards">' + doc.chain.map((s) =>
      '<div class="card"><h3>' + esc(s.source) + "</h3><p>" + esc(s.note || "") +
      "</p></div>").join("") + "</div>" +
    "<p class=\"muted\">Providers are tried in the order an instrument lists them. " +
    "A price that cannot be fetched is never invented: the instrument simply has no " +
    "price that day, cannot be traded, and is held at cost.</p>" + short;
}

async function evolutionPanel() {
  const text = await get("evolution-latest.md", "");
  const state = await get("evolution.json", null);
  if (!text) {
    if (state && state.outcome === "refused") {
      $("evolution").innerHTML = "<p>The last rewrite was <b>refused</b> by the desk: " +
        esc(state.why || "") + " The brief stands unchanged.</p>";
    }
    return;
  }
  const lines = text.split("\n");
  const head = lines[0].replace(/^#\s*/, "");
  const body = lines.slice(1).join("\n");
  $("evolution").innerHTML = '<div class="thread"><h3>' + esc(head) + "</h3>" +
    "<pre class=\"record\">" + esc(body.trim().slice(0, 2600)) + "</pre>" +
    '<p class="muted">Full record, including the diff, in ' +
    "<code>company/evolution/</code>.</p></div>";
}

async function standingsPage() {
  const board = await get("leaderboard.json", null);
  if (!board || !board.rows || !board.rows.length) {
    empty($("standings"), "The desk has not opened yet.");
  } else {
    $("standings").innerHTML = standingsTable(board);
    $("as-of").textContent = "as of " + (board.date || "");
    const series = {}, names = {};
    for (const row of board.rows) {
      const s = await get("nav/" + row.advisor + ".json", { series: [] });
      series[row.advisor] = s.series || [];
      names[row.advisor] = row.name;
    }
    $("nav-chart").outerHTML = navChart(series, names);
    const note = $("chart-note");
    if (note) note.textContent =
      "The dashed line is the $100,000 every advisor started with. Imaginary money.";
  }
  await Promise.all([sourcesPanel(), evolutionPanel()]);
}

/* ---- the book ------------------------------------------------------- */

async function deskPage() {
  const day = await get("orders-latest.json", null);
  const prices = await get("prices-latest.json", { quotes: {} });
  const board = await get("leaderboard.json", { rows: [] });
  const roster = await get("roster.json", []);
  const who = {};
  roster.forEach((p) => { who[p.id] = p; });

  if (!day) { empty($("today"), "No trading day on file yet."); }
  else {
    $("desk-date").textContent = day.date || "";
    const blocks = Object.keys(day.advisors).sort().map((id) => {
      const rec = day.advisors[id];
      const name = (who[id] && who[id].name) || id;
      if (rec.held) {
        // held is an object: {kind, why}. An older record may hold a bare string,
        // which always meant "unreachable".
        const kind = (typeof rec.held === "object" && rec.held) ? rec.held.kind
                                                                : "unreachable";
        const why = (typeof rec.held === "object" && rec.held) ? (rec.held.why || "")
                                                               : String(rec.held);
        const said = {
          unreachable: "Could not be reached, and held.",
          chose_to_hold: "Sent no orders today.",
          all_rejected: "Asked, and every order was refused."
        }[kind] || "Held.";
        return '<div class="card"><h3>' + esc(name) + "</h3><p>" + esc(said) +
          (why ? ' <span class="muted">' + esc(why) + "</span>" : "") + "</p></div>";
      }
      const orders = (rec.orders || []).map((o) =>
        '<li><b class="' + (o.action === "buy" ? "up" : "down") + '">' + esc(o.action) +
        "</b> " + money(o.amount_usd) + " " + esc(o.instrument) +
        ' <span class="muted">— ' + esc(o.reason) + "</span></li>").join("");
      const refused = (rec.rejected || []).map((r) =>
        '<li class="refused">refused: ' + esc(r.why) + "</li>").join("");
      return '<div class="card"><h3>' + esc(name) + "</h3>" +
        (rec.note ? "<p>" + esc(rec.note) + "</p>" : "") +
        (orders || refused ? "<ul class=\"orders\">" + orders + refused + "</ul>"
                           : '<p class="muted">No orders.</p>') + "</div>";
    }).join("");
    $("today").innerHTML = '<div class="cards">' + blocks + "</div>";
  }

  const books = [];
  for (const row of board.rows || []) {
    const book = await get("portfolios/" + row.advisor + ".json", null);
    if (!book) continue;
    const held = Object.keys(book.positions || {}).sort();
    const rows = held.map((sym) => {
      const p = book.positions[sym];
      const q = prices.quotes[sym];
      const worth = q ? p.qty * q.close : p.cost;
      const ret = p.cost ? (worth / p.cost - 1) * 100 : 0;
      return "<tr><td>" + esc(sym) + '</td><td class="num">' + money(p.cost) +
        '</td><td class="num">' + money(worth) + '</td><td class="num ' + cls(ret) +
        '">' + pct(ret) + "</td>" +
        (q ? "" : '<td class="muted">no price today</td>') + "</tr>";
    }).join("");
    books.push('<div class="thread"><h3>' + esc(row.name) + " — " + money(row.nav) +
      ' <span class="' + cls(row.return_pct) + '">' + pct(row.return_pct) + "</span></h3>" +
      '<p class="muted">Cash ' + money(book.cash) + "</p>" +
      (held.length
        ? '<div class="scroller"><table class="grid"><thead><tr><th>Instrument</th>' +
          '<th class="num">Cost</th><th class="num">Now</th><th class="num">Return</th>' +
          "</tr></thead><tbody>" + rows + "</tbody></table></div>"
        : '<p class="empty">All cash.</p>') + "</div>");
  }
  if (books.length) $("books").innerHTML = books.join("");
  else empty($("books"), "No books yet.");

  const quotes = prices.quotes || {};
  const syms = Object.keys(quotes).sort();
  if (syms.length) {
    const byClass = {};
    syms.forEach((s) => {
      (byClass[quotes[s].class] = byClass[quotes[s].class] || []).push(s);
    });
    $("prices").innerHTML = Object.keys(byClass).sort().map((k) =>
      '<div class="thread"><h3>' + esc(k) + "</h3><div class=\"scroller\">" +
      '<table class="grid"><tbody>' + byClass[k].map((s) =>
        "<tr><td>" + esc(s) + "</td><td>" + esc(quotes[s].name) +
        '</td><td class="num">' + Number(quotes[s].close).toLocaleString("en-US",
          { maximumFractionDigits: 5 }) + '</td><td class="muted">' +
        esc(quotes[s].source) + "</td></tr>").join("") +
      "</tbody></table></div></div>").join("");
  } else empty($("prices"), "No prices on file.");
}

/* ---- the floor ------------------------------------------------------ */

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const LONG = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday",
               fri: "Friday", sat: "Saturday", sun: "Sunday" };

function desk(person, today) {
  const shifts = Array.isArray(person.shifts) ? person.shifts : [];
  const on = shifts.indexOf(today) !== -1;
  const week = DAYS.map((d) => '<span class="' + (shifts.indexOf(d) !== -1 ? "on" : "off") +
    '">' + d.charAt(0).toUpperCase() + d.slice(1) + "</span>").join("");
  return '<div class="desk' + (on ? " on" : "") + '">' +
    '<img src="data/avatars/' + esc(person.id) + '.svg" alt="" width="56" height="56" ' +
    'onerror="this.hidden=true">' +
    "<b>" + esc(person.name) + "</b>" +
    '<span class="muted">' + esc(person.title) + "</span>" +
    "<p>" + esc(person.bio) + "</p>" +
    (person.mandate ? '<p class="mandate">' + esc(person.mandate) + "</p>" : "") +
    '<div class="week">' + week + "</div>" +
    '<span class="muted">' + (on ? "At their desk today" : "Next in on " +
      (LONG[shifts[0]] || "—")) + "</span>" +
    '<a class="muted" href="data/prompts/' + esc(person.id) +
    '.md">read their brief</a></div>';
}

async function officePage() {
  const roster = await get("roster.json", []);
  const today = DAYS[(new Date().getDay() + 6) % 7];
  if (!roster.length) { empty($("floor"), "No roster on file."); }
  else {
    const rooms = {};
    roster.forEach((p) => { (rooms[p.room] = rooms[p.room] || []).push(p); });
    $("floor").innerHTML = Object.keys(rooms).map((room) =>
      '<div class="room"><h3>' + esc(room) + "</h3>" +
      '<div class="desks">' + rooms[room].map((p) => desk(p, today)).join("") +
      "</div></div>").join("");
    const n = roster.filter((p) => (p.shifts || []).indexOf(today) !== -1).length;
    $("today-line").textContent = "— " + LONG[today] + ", " + n + " on shift";
  }

  const names = {};
  roster.forEach((p) => { names[p.id] = p; });
  const list = (await manifest()).files.filter((f) => f.indexOf("hallway/") === 0);
  const said = [];
  for (const file of list.slice(-14).reverse()) {
    const text = (await get(file, "")).trim();
    if (!text) continue;
    const stem = file.split("/").pop().replace(/\.txt$/, "");
    const at = stem.indexOf("-", 8);
    const date = stem.slice(0, at), id = stem.slice(at + 1);
    const p = names[id] || { name: id, title: "" };
    said.push('<div class="bubble"><div class="meta"><b>' + esc(p.name) + "</b> · " +
      esc(p.title) + " · " + esc(date) + '</div><div class="said"><p>' +
      esc(text) + "</p></div></div>");
  }
  if (said.length) $("hallway-feed").innerHTML = said.join("");

  const notes = (await manifest()).files
    .filter((f) => f.indexOf("minutes/") === 0 || f.indexOf("evolution/") === 0)
    .sort().reverse().slice(0, 12);
  const blocks = [];
  for (const file of notes) {
    const text = await get(file, "");
    if (!text) continue;
    const lines = text.split("\n");
    blocks.push('<details class="thread"><summary>' +
      esc(lines[0].replace(/^#\s*/, "")) + "</summary><pre class=\"record\">" +
      esc(lines.slice(1).join("\n").trim().slice(0, 6000)) + "</pre></details>");
  }
  if (blocks.length) $("minutes").innerHTML = blocks.join("");
}

/* ---- changelog ------------------------------------------------------ */

async function changelogPage() {
  const entries = await get("changelog.json", []);
  if (!entries.length) { empty($("changelog"), "Nothing merged yet."); return; }
  $("changelog").innerHTML = '<div class="scroller"><table class="grid"><tbody>' +
    entries.map((e) => "<tr><td class=\"muted\">" + esc(e.date) + "</td><td>" +
      esc(e.message) + "</td></tr>").join("") + "</tbody></table></div>";
}

/* ---- boot ----------------------------------------------------------- */

(async function () {
  await companyName();
  try {
    if ($("standings")) await standingsPage();
    if ($("today")) await deskPage();
    if ($("floor")) await officePage();
    if ($("changelog")) await changelogPage();
  } catch (e) {
    /* A page that throws must still show its disclaimers, which live in the
       HTML rather than here for exactly this reason. */
    if (window.console) console.error(e);
  }
})();
