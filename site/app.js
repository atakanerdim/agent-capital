"use strict";
(function () {

  /* ------------------------------------------------------------------
     Live data. Every one of these is filled by boot() from a file the desk
     publishes after the close. A view whose file is missing or malformed
     keeps its designed empty state, and no view can take another one down.
     ------------------------------------------------------------------ */

  let STANDINGS = [];
  let NAV_DATES = [];
  let NAV_SERIES = {};
  let TODAY = [];
  let TODAY_AS_OF = "";
  let BOOK = null;
  let ROSTER = {advisors: [], staff: []};

  /* ------------------------------------------------------------------ */

  /* Portraits. `src` is a local file dropped in beside this page — never a URL.
     Until one exists the slot prints the advisor's initials as a misregistered
     two-plate monogram, so the layout never shifts when the photograph lands. */
  let PORTRAITS = {};

  /* Largest holdings per book, for the expanded row. */
  let HOLDS = {};

  /* One character per weekday: m moved, h held, r all refused, u unreachable. */
  let RECORD = {};

  /* What each book held at each close: {advisor: {slots, days:[{date, cash, parts}]}}. */
  let ALLOC = {};
  let INSTR = {};
  let SWEEP = null;
  const RECORD_KEY = {m:"moved", h:"held", r:"refused", u:"unreachable"};

  const $ = function (sel, root) { return (root || document).querySelector(sel); };
  const tpl = function (id) { return document.getElementById(id).content.firstElementChild.cloneNode(true); };
  const svgTpl = function (id) { return document.getElementById(id).content.querySelector("svg").cloneNode(true); };

  const usd0 = new Intl.NumberFormat("en-US", {style:"currency", currency:"USD", maximumFractionDigits:0});
  const usd2 = new Intl.NumberFormat("en-US", {style:"currency", currency:"USD", minimumFractionDigits:2, maximumFractionDigits:2});
  const num = new Intl.NumberFormat("en-US", {maximumFractionDigits:2});

  function pct(v) {
    const s = v > 0 ? "+" : (v < 0 ? "\u2212" : "");
    return s + Math.abs(v).toFixed(2) + "%";
  }

  /* A delta always carries three cues: an arrow shape, a sign, and a colour. */
  function delta(v, opts) {
    const span = document.createElement("span");
    const dir = v > 0 ? "up" : (v < 0 ? "down" : "flat");
    span.className = "delta " + dir;
    span.appendChild(svgTpl(dir === "up" ? "tpl-up" : (dir === "down" ? "tpl-down" : "tpl-flat")));
    const sr = document.createElement("span");
    sr.className = "sr";
    sr.textContent = dir === "up" ? "up " : (dir === "down" ? "down " : "unchanged ");
    span.appendChild(sr);
    const val = document.createElement("span");
    val.textContent = pct(v);
    if (opts && opts.big) { val.style.fontSize = "inherit"; }
    span.appendChild(val);
    return span;
  }

  function ddText(v) {
    return v > 0.004 ? "\u2212" + v.toFixed(2) + "%" : "0.00%";
  }

  function longDate(iso) {
    const parts = iso.split("-");
    const months = ["January","February","March","April","May","June","July","August",
      "September","October","November","December"];
    return Number(parts[2]) + " " + months[Number(parts[1]) - 1];
  }

  function bookHref(key) { return "desk.html?a=" + encodeURIComponent(key) + "#advisor"; }

  function shortDate(iso) {
    const parts = iso.split("-");
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return Number(parts[2]) + " " + months[Number(parts[1]) - 1];
  }

  function byKey(key) {
    for (let i = 0; i < STANDINGS.length; i++) { if (STANDINGS[i].advisor === key) { return STANDINGS[i]; } }
    return null;
  }
  function roleOf(key) {
    for (let i = 0; i < ROSTER.advisors.length; i++) { if (ROSTER.advisors[i].advisor === key) { return ROSTER.advisors[i].role; } }
    return "";
  }

  /* ---------------- standings ---------------- */

  function renderSummary(rows) {
    const host = $("#summary");
    host.textContent = "";
    const bench = rows.filter(function (r) { return r.is_benchmark; })[0];
    const advisors = rows.filter(function (r) { return !r.is_benchmark; });
    const ahead = advisors.filter(function (r) { return bench && r.return_pct > bench.return_pct; }).length;
    const best = advisors[0];
    const worst = advisors[advisors.length - 1];

    const items = [
      {label:"Beating buy and hold", node:document.createTextNode(ahead + " of " + advisors.length),
       note:"Advisors ahead of a book that never trades."},
      {label:"Buy and hold", node:delta(bench ? bench.return_pct : 0),
       note:"The benchmark: every instrument the desk may touch, bought on day one."},
      {label:"Best book", node:delta(best.return_pct), note:best.name + " \u00b7 " + usd0.format(best.nav)},
      {label:"Worst book", node:delta(worst.return_pct), note:worst.name + " \u00b7 " + usd0.format(worst.nav)}
    ];

    items.forEach(function (it) {
      const node = tpl("tpl-summary-item");
      $("dt", node).textContent = it.label;
      $(".val", node).appendChild(it.node);
      $("small", node).textContent = it.note;
      host.appendChild(node);
    });
  }

  function portraitNode(key, name, size) {
    const p = tpl("tpl-portrait");
    if (size) { p.classList.add(size); }
    const info = PORTRAITS[key];
    if (info && info.src) {
      p.textContent = "";
      const img = document.createElement("img");
      img.setAttribute("src", info.src);
      img.setAttribute("alt", "");
      p.appendChild(img);
    } else if (info) {
      $(".init", p).textContent = info.initials;
      if (info.sample && size === "lg") { p.classList.add("photo"); }
    } else {
      p.classList.add("none");
      p.textContent = "";
      const dash = document.createElement("span");
      dash.className = "dash";
      p.appendChild(dash);
    }
    return p;
  }

  /* A per-book sparkline: the advisor in ink-cyan (magenta when the book is
     under water), the benchmark dashed behind it, the opening $100,000 dotted. */
  function sparkline(key) {
    const s = NAV_SERIES[key];
    const b = NAV_SERIES.benchmark;
    if (!s) { return null; }
    const W = 300, H = 66, top = 6, bot = 8;
    let lo = Infinity, hi = -Infinity;
    s.concat(b || []).concat([100000]).forEach(function (v) {
      if (v < lo) { lo = v; }
      if (v > hi) { hi = v; }
    });
    const span = (hi - lo) || 1;
    lo -= span * 0.08; hi += span * 0.08;
    const n = s.length;
    const x = function (i) { return i * W / (n - 1); };
    const y = function (v) { return top + (hi - v) * (H - top - bot) / (hi - lo); };
    const down = s[n - 1] < s[0];

    const svg = sv("svg", {class:"spark", viewBox:"0 0 " + W + " " + H, preserveAspectRatio:"none",
      role:"img", "aria-hidden":"true"});

    let d = "";
    s.forEach(function (v, i) { d += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " "; });
    svg.appendChild(sv("path", {class:"sk-fill" + (down ? " down" : ""),
      d:d + "L" + W + " " + (H - bot) + " L0 " + (H - bot) + " Z"}));
    svg.appendChild(sv("line", {class:"sk-base", x1:0, y1:y(100000), x2:W, y2:y(100000)}));
    if (b && key !== "benchmark") {
      let db = "";
      b.forEach(function (v, i) { db += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " "; });
      svg.appendChild(sv("path", {class:"sk-bench", d:db.trim()}));
    }
    svg.appendChild(sv("path", {class:"sk-line" + (down ? " down" : ""), d:d.trim()}));
    svg.appendChild(sv("circle", {class:"sk-dot" + (down ? " down" : ""),
      cx:x(n - 1) - 2, cy:y(s[n - 1]), r:3}));
    return svg;
  }

  /* ---------------- what a book holds: the pie and its history ----------------
     One component, drawn in three sizes. The pie is today's close; the columns
     under it are every close so far, each one the whole book, so a reader sees
     both what an advisor owns and how they got there. Colours are handed out per
     book in a fixed order (largest position the book has ever carried first) and
     never re-dealt from day to day, so an instrument keeps its colour across the
     whole history. Past seven, the rest fold into "Other". Cash is always the
     pale neutral slice. Every colour sits next to a written label and a figure. */

  const SLOT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"];
  const OTHER_COLOR = "#8a8786";
  const CASH_COLOR = "#d6d3d2";

  function mixOf(key, day) {
    const a = ALLOC[key];
    const total = day.cash + Object.keys(day.parts).reduce(function (t, k) { return t + day.parts[k]; }, 0);
    const out = [];
    let other = 0, otherN = 0;
    Object.keys(day.parts).forEach(function (sym) {
      if (a.slots.indexOf(sym) < 0) { other += day.parts[sym]; otherN += 1; }
    });
    a.slots.forEach(function (sym, i) {
      if (day.parts[sym]) {
        out.push({key:sym, label:sym, name:(INSTR[sym] || {}).name || sym,
                  value:day.parts[sym], color:SLOT_COLORS[i]});
      }
    });
    if (other > 0) {
      out.push({key:"__other", label:"Other", name:otherN + " more holding" + (otherN === 1 ? "" : "s"), value:other, color:OTHER_COLOR});
    }
    if (day.cash > 0.5) {
      out.push({key:"__cash", label:"Cash", name:SWEEP ? "T-bill sweep, " + SWEEP.pct.toFixed(2) + "%" :
        "uninvested", value:day.cash, color:CASH_COLOR});
    }
    out.forEach(function (p) { p.share = total ? p.value / total : 0; });
    return {parts:out, total:total};
  }

  function shareText(x) {
    const v = x * 100;
    return (v > 0 && v < 1 ? "<1" : (v >= 99.5 && v < 100 ? ">99" : Math.round(v))) + "%";
  }

  /* One tooltip for the whole page, positioned on the pointer. */
  let TIP = null;
  function tipFor(el, text) {
    el.setAttribute("data-tip", text);
    el.addEventListener("pointerenter", showTip);
    el.addEventListener("pointermove", moveTip);
    el.addEventListener("pointerleave", hideTip);
  }
  function showTip(e) {
    if (!TIP) {
      TIP = document.createElement("div");
      TIP.className = "tip";
      TIP.setAttribute("role", "tooltip");
      document.body.appendChild(TIP);
    }
    TIP.textContent = e.currentTarget.getAttribute("data-tip");
    TIP.hidden = false;
    moveTip(e);
  }
  function moveTip(e) {
    if (!TIP) { return; }
    const pad = 14;
    const w = TIP.offsetWidth, h = TIP.offsetHeight;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > window.innerWidth - 8) { x = e.clientX - w - pad; }
    if (y + h > window.innerHeight - 8) { y = e.clientY - h - pad; }
    TIP.style.left = Math.max(8, x) + "px";
    TIP.style.top = Math.max(8, y) + "px";
  }
  function hideTip() { if (TIP) { TIP.hidden = true; } }

  function arcPath(cx, cy, r0, r1, a0, a1) {
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const p = function (r, a) { return (cx + r * Math.sin(a)).toFixed(2) + " " + (cy - r * Math.cos(a)).toFixed(2); };
    return "M" + p(r1, a0) + " A" + r1 + " " + r1 + " 0 " + large + " 1 " + p(r1, a1) +
      " L" + p(r0, a1) + " A" + r0 + " " + r0 + " 0 " + large + " 0 " + p(r0, a0) + " Z";
  }

  function donut(mix, size, caption) {
    const r1 = size / 2 - 1, r0 = r1 * 0.62, c = size / 2;
    const svg = sv("svg", {class:"donut", viewBox:"0 0 " + size + " " + size, width:size, height:size,
      role:"img", "aria-label":caption});
    let a = 0;
    mix.parts.forEach(function (p) {
      const sweep = p.share * Math.PI * 2;
      let el;
      if (p.share >= 0.9999) {
        el = sv("path", {d:"M" + c + " " + (c - r1) + " A" + r1 + " " + r1 + " 0 1 1 " + (c - 0.01) + " " + (c - r1) +
          " Z M" + c + " " + (c - r0) + " A" + r0 + " " + r0 + " 0 1 0 " + (c + 0.01) + " " + (c - r0) + " Z",
          "fill-rule":"evenodd"});
      } else {
        el = sv("path", {d:arcPath(c, c, r0, r1, a, a + sweep)});
      }
      el.setAttribute("fill", p.color);
      el.setAttribute("class", "slice" + (p.key === "__cash" ? " cash" : ""));
      tipFor(el, p.label + (p.key.indexOf("__") ? " · " + p.name : "") + " — " +
        usd0.format(p.value) + " (" + shareText(p.share) + ")");
      svg.appendChild(el);
      a += sweep;
    });
    const invested = mix.parts.filter(function (p) { return p.key !== "__cash"; })
      .reduce(function (t, p) { return t + p.share; }, 0);
    /* Sized from the hole, not the page: the label has to fit inside r0 in any
       font the reader's machine falls back to, so it is scaled and never spaced. */
    const bigPx = Math.round(r0 * 0.5), smallPx = Math.max(10, Math.round(r0 * 0.22));
    const big = sv("text", {x:c, y:c + bigPx * 0.2, "text-anchor":"middle", class:"d-big",
      "font-size":bigPx});
    big.textContent = shareText(invested);
    const small = sv("text", {x:c, y:c + bigPx * 0.2 + smallPx + 3, "text-anchor":"middle",
      class:"d-small", "font-size":smallPx});
    small.textContent = "in markets";
    svg.appendChild(big);
    svg.appendChild(small);
    return svg;
  }

  function legendList(mix, limit) {
    const ul = document.createElement("ul");
    ul.className = "alegend";
    let rows = mix.parts;
    if (limit && rows.length > limit) {
      const cash = rows.filter(function (p) { return p.key === "__cash"; });
      rows = rows.filter(function (p) { return p.key !== "__cash"; }).slice(0, limit - cash.length).concat(cash);
    }
    rows.forEach(function (p) {
      const li = document.createElement("li");
      const sw = document.createElement("i");
      sw.style.background = p.color;
      if (p.key === "__cash") { sw.className = "cash"; }
      const b = document.createElement("b");
      b.textContent = p.label;
      const nm = document.createElement("span");
      nm.className = "an";
      nm.textContent = p.name;
      const v = document.createElement("span");
      v.className = "av num";
      v.textContent = shareText(p.share);
      li.appendChild(sw); li.appendChild(b); li.appendChild(nm); li.appendChild(v);
      ul.appendChild(li);
    });
    return ul;
  }

  function historyColumns(key, height) {
    const a = ALLOC[key];
    const days = a.days.slice(-66);
    const n = days.length;
    const W = 240, H = height, gap = n > 30 ? 1 : 3;
    const cw = Math.min(26, (W - gap * (n - 1)) / n);
    const used = n * cw + gap * (n - 1);
    const wrap = document.createElement("div");
    wrap.className = "ahist";
    const svg = sv("svg", {viewBox:"0 0 " + used.toFixed(1) + " " + H, width:used.toFixed(1), height:H,
      preserveAspectRatio:"none", role:"img",
      "aria-label":"Holdings at each close, oldest first, " + n + " day" + (n === 1 ? "" : "s")});
    days.forEach(function (day, i) {
      const mix = mixOf(key, day);
      const x = i * (cw + gap);
      let yTop = H;
      const g = sv("g", {class:"col"});
      /* instruments from the floor up, cash on top: a rising floor is a book getting invested */
      const order = mix.parts.filter(function (p) { return p.key !== "__cash"; })
        .concat(mix.parts.filter(function (p) { return p.key === "__cash"; }));
      order.forEach(function (p) {
        const h = p.share * H;
        if (h <= 0) { return; }
        yTop -= h;
        g.appendChild(sv("rect", {x:x.toFixed(1), y:yTop.toFixed(2), width:cw.toFixed(1),
          height:Math.max(0, h - (h > 2 ? 1 : 0)).toFixed(2), fill:p.color,
          class:p.key === "__cash" ? "cash" : ""}));
      });
      g.appendChild(sv("rect", {x:x.toFixed(1), y:0, width:cw.toFixed(1), height:H, class:"hit"}));
      tipFor(g, shortDate(day.date) + " · " + usd0.format(mix.total) + " — " +
        mix.parts.map(function (p) { return p.label + " " + shareText(p.share); }).join(", "));
      svg.appendChild(g);
    });
    wrap.appendChild(svg);
    const axis = document.createElement("div");
    axis.className = "ahist-axis";
    const l = document.createElement("span");
    l.textContent = shortDate(days[0].date);
    const r = document.createElement("span");
    r.textContent = n > 1 ? shortDate(days[n - 1].date) : "";
    axis.appendChild(l); axis.appendChild(r);
    axis.style.width = Math.max(used, 96).toFixed(1) + "px";
    wrap.appendChild(axis);
    return wrap;
  }

  /* size: "row" (standings), "card" (the desk page), "day" (today), "book" (the book page) */
  function allocBlock(key, size) {
    const a = ALLOC[key];
    if (!a || !a.days || !a.days.length) { return null; }
    const last = a.days[a.days.length - 1];
    const mix = mixOf(key, last);
    const px = {row:176, card:168, day:150, book:240}[size] || 160;
    const host = document.createElement("div");
    host.className = "alloc alloc-" + size;

    const pie = document.createElement("div");
    pie.className = "apie";
    const caption = "Holdings at the close, " + shortDate(last.date) + ": " +
      mix.parts.map(function (p) { return p.label + " " + shareText(p.share); }).join(", ") + ".";
    pie.appendChild(donut(mix, px, caption));
    host.appendChild(pie);

    const side = document.createElement("div");
    side.className = "aside";
    const h = document.createElement("h4");
    h.className = "ahead";
    h.textContent = "Holdings at the close, " + shortDate(last.date);
    side.appendChild(h);
    side.appendChild(legendList(mix, size === "day" || size === "card" ? 6 : 0));
    host.appendChild(side);

    if (size !== "day") {
      const hist = document.createElement("div");
      hist.className = "ahistbox";
      const hh = document.createElement("h4");
      hh.className = "ahead";
      hh.textContent = a.history ? "Every close so far" : "History not shown";
      hist.appendChild(hh);
      if (a.history) {
        hist.appendChild(historyColumns(key, size === "book" ? 120 : (size === "card" ? 48 : 64)));
        const note = document.createElement("p");
        note.className = "anote";
        note.textContent = changeLine(key);
        hist.appendChild(note);
      } else {
        const note = document.createElement("p");
        note.className = "anote";
        note.textContent = "The recorded orders do not rebuild today’s book exactly, so only today is drawn.";
        hist.appendChild(note);
      }
      host.appendChild(hist);
    }
    return host;
  }

  /* One sentence on how the mix moved, from the first close to the last. */
  function changeLine(key) {
    const a = ALLOC[key];
    const days = a.days;
    if (days.length < 2) { return "One close so far."; }
    const first = days[0], last = days[days.length - 1];
    const inv = function (d) {
      const t = d.cash + Object.keys(d.parts).reduce(function (s, k) { return s + d.parts[k]; }, 0);
      return t ? 1 - d.cash / t : 0;
    };
    const opened = Object.keys(last.parts).filter(function (s) { return !(s in first.parts); });
    const closed = Object.keys(first.parts).filter(function (s) { return !(s in last.parts); });
    const bits = [];
    bits.push("In markets " + shareText(inv(first)) + " on " + shortDate(first.date) + ", " +
      shareText(inv(last)) + " on " + shortDate(last.date) + "; the rest earned the T-bill sweep.");
    if (opened.length) { bits.push("Added " + opened.join(", ") + "."); }
    if (closed.length) { bits.push("Closed " + closed.join(", ") + "."); }
    if (!opened.length && !closed.length && !Object.keys(last.parts).length) {
      bits.push("Never held a position.");
    }
    return bits.join(" ");
  }

  function todayLine(key) {
    if (key === "benchmark") {
      return "Nothing. This book has never placed an order and never will \u2014 that is the point of it.";
    }
    const d = TODAY.filter(function (t) { return t.advisor === key; })[0];
    if (!d) { return "No entry published for today."; }
    if (d.held) {
      const head = OUTCOMES[d.held.kind] ? OUTCOMES[d.held.kind].text : "Held";
      const why = d.note || (d.held.why && d.held.why !== GENERIC_HOLD ? d.held.why : "");
      return head + "." + (why ? " " + why : "");
    }
    const parts = (d.orders || []).map(function (o) {
      return (o.action === "buy" ? "Bought " : "Sold ") + usd0.format(o.amount_usd) + " of " + o.instrument;
    });
    return parts.join(" and ") + ". " + (d.note || (d.orders[0] && d.orders[0].reason) || "");
  }

  function markStrip(host, chars) {
    host.textContent = "";
    chars.split("").forEach(function (c, i) {
      const kind = RECORD_KEY[c];
      if (!kind) { return; }
      const m = tpl("tpl-mark");
      m.classList.add("mk-" + kind);
      m.setAttribute("title", "Day " + (i + 1) + " \u2014 " + RECORD_LABEL[kind]);
      $(".sr", m).textContent = "Day " + (i + 1) + ": " + RECORD_LABEL[kind] + ". ";
      host.appendChild(m);
    });
  }

  function detailRow(r) {
    const row = tpl("tpl-drow");
    row.id = "detail-" + r.advisor;

    const sp = sparkline(r.advisor);
    if (sp) { $(".sparkhost", row).appendChild(sp); }
    const since = $(".sincehead", row);
    if (since && NAV_DATES.length) { since.textContent = "Since " + shortDate(NAV_DATES[0]); }
    const bench = byKey("benchmark");
    const gap = bench ? r.return_pct - bench.return_pct : 0;
    $(".sparknote", row).textContent = usd2.format(r.nav) + " today, " + pct(r.return_pct) +
      " since the open. Against buy and hold: " + pct(gap) + ". Deepest fall from a peak " +
      ddText(r.max_drawdown_pct) + ".";

    $(".dmandate", row).textContent = r.mandate;
    $(".dtoday", row).textContent = todayLine(r.advisor);

    const chips = $(".chips", row);
    const holds = HOLDS[r.advisor];
    if (holds && holds.length) {
      holds.forEach(function (p) {
        const c = tpl("tpl-chip");
        $("b", c).textContent = p.instrument;
        $(".cv", c).appendChild(delta(p.return_pct));
        chips.appendChild(c);
      });
    } else {
      chips.textContent = r.is_benchmark
        ? "Every instrument, equally weighted, untouched since day one."
        : "No positions. The whole book is in cash.";
      chips.style.fontSize = "14px";
    }

    const rec = RECORD[r.advisor];
    if (rec) { markStrip($(".strip", row), rec); }
    else {
      $(".rechead", row).textContent = "Record, day by day";
      $(".strip", row).textContent = "No decisions to record.";
      $(".strip", row).style.fontSize = "14px";
    }
    return row;
  }

  function renderLeader(rows) {
    const r = rows.filter(function (x) { return !x.is_benchmark; })[0];
    const host = $("#leader");
    if (!r || !host) { return; }
    const slot = $("#leader-pslot");
    if (slot) { slot.replaceWith(portraitNode(r.advisor, r.name, "lg")); }
    $("#leader-name").textContent = r.name;
    $("#leader-role").textContent = roleOf(r.advisor) + " mandate";
    $("#leader-line").textContent = todayLine(r.advisor);
    $("#leader-nav").textContent = usd0.format(r.nav);
    const ret = $("#leader-ret");
    ret.textContent = "";
    ret.appendChild(delta(r.return_pct));
    const sp = sparkline(r.advisor);
    const sph = $("#leader-spark");
    sph.textContent = "";
    if (sp) { sph.appendChild(sp); }
    host.hidden = false;
  }

  function renderStandings(rows) {
    const body = $("#standings-body");
    body.textContent = "";
    rows.forEach(function (r, i) {
      const tr = tpl("tpl-standings-row");
      if (r.is_benchmark) { tr.className = "is-benchmark"; }
      $(".c-rank", tr).textContent = String(i + 1);

      const link = $(".who a", tr);
      link.textContent = r.name;
      link.setAttribute("href", bookHref(r.advisor));
      $(".role-sm", tr).textContent = r.is_benchmark ? "Benchmark" : roleOf(r.advisor);
      $(".pslot", tr).replaceWith(portraitNode(r.is_benchmark ? "__none" : r.advisor, r.name));

      if (r.is_benchmark) {
        const tag = $(".tag", tr);
        tag.hidden = false;
        tag.className = "tag tag-ink";
        tag.textContent = "Benchmark \u2014 not an advisor";
        const note = $(".bench-note", tr);
        note.hidden = false;
        note.textContent = "No advisor, no decisions, no orders. It is here to be beaten.";
        link.replaceWith(document.createTextNode(r.name));
      }

      $(".c-nav", tr).textContent = usd2.format(r.nav);
      $(".c-ret", tr).appendChild(delta(r.return_pct));
      $(".c-days", tr).appendChild(document.createTextNode(String(r.days)));
      $(".c-dd", tr).appendChild(document.createTextNode(ddText(r.max_drawdown_pct)));
      $(".c-best", tr).appendChild(delta(r.best_day_pct));
      $(".c-worst", tr).appendChild(delta(r.worst_day_pct));

      const drow = detailRow(r);
      const btn = $("button.more", tr);
      btn.setAttribute("aria-controls", drow.id);
      $(".mtext", btn).textContent = "Open";
      btn.addEventListener("click", function () {
        const open = btn.getAttribute("aria-expanded") === "true";
        btn.setAttribute("aria-expanded", open ? "false" : "true");
        drow.hidden = open;
      });

      body.appendChild(tr);
      const block = allocBlock(r.advisor, "row");
      if (block) {
        const prow = tpl("tpl-prow");
        if (r.is_benchmark) { prow.classList.add("is-benchmark-p"); }
        $("td", prow).appendChild(block);
        body.appendChild(prow);
        tr.classList.add("has-prow");
      }
      body.appendChild(drow);
    });
  }

  /* ---------------- chart (inline SVG, no library) ---------------- */

  const SVGNS = "http://www.w3.org/2000/svg";
  let highlight = "value";

  function sv(name, attrs) {
    const e = document.createElementNS(SVGNS, name);
    for (const k in attrs) { e.setAttribute(k, String(attrs[k])); }
    return e;
  }

  function drawChart() {
    const host = $("#chart-host");
    if (!host) { return; }
    host.textContent = "";
    const keys = Object.keys(NAV_SERIES);
    if (!keys.length || !NAV_DATES.length) { return; }

    const w = Math.max(300, host.clientWidth || 360);
    const narrow = w < 560;
    const h = narrow ? 190 : 260;
    const padL = 58, padR = narrow ? 14 : 74, padT = 14, padB = 26;

    let lo = Infinity, hi = -Infinity;
    keys.forEach(function (k) {
      NAV_SERIES[k].forEach(function (v) { if (v < lo) { lo = v; } if (v > hi) { hi = v; } });
    });
    const span = (hi - lo) || 1;
    lo -= span * 0.06; hi += span * 0.06;

    const n = NAV_DATES.length;
    const x = function (i) { return padL + i * (w - padL - padR) / (n - 1); };
    const y = function (v) { return padT + (hi - v) * (h - padT - padB) / (hi - lo); };

    const svg = sv("svg", {viewBox:"0 0 " + w + " " + h, width:"100%", height:h, class:"chart",
      role:"img", "aria-labelledby":"chart-caption"});

    svg.appendChild(sv("line", {class:"axis", x1:padL, y1:padT, x2:padL, y2:h - padB}));

    /* Tick labels carry as many decimals as the range needs: on a day when every
       book is within a few hundred dollars of the open, "100k" three times over
       says nothing. Labels closer than 14px to one already drawn are dropped. */
    const digits = span < 2000 ? 2 : (span < 20000 ? 1 : 0);
    const kfmt = function (v) { return "$" + (v / 1000).toFixed(digits) + "k"; };
    const drawn = [];
    const tick = function (v) {
      const yy = y(v);
      if (drawn.some(function (d) { return Math.abs(d - yy) < 14; })) { return; }
      drawn.push(yy);
      const t = sv("text", {x:padL - 6, y:yy + 3.5, "text-anchor":"end"});
      t.textContent = kfmt(v);
      svg.appendChild(t);
    };
    /* the opening $100,000 */
    if (100000 > lo && 100000 < hi) {
      svg.appendChild(sv("line", {class:"base", x1:padL, y1:y(100000), x2:w - padR, y2:y(100000)}));
      tick(100000);
    }
    tick(hi - span * 0.03);
    tick(lo + span * 0.03);

    const path = function (arr) {
      let d = "";
      arr.forEach(function (v, i) { d += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " "; });
      return d.trim();
    };

    keys.forEach(function (k) {
      if (k === "benchmark" || k === highlight) { return; }
      svg.appendChild(sv("path", {class:"ln", d:path(NAV_SERIES[k])}));
    });
    if (NAV_SERIES.benchmark && highlight !== "benchmark") {
      svg.appendChild(sv("path", {class:"ln-bench", d:path(NAV_SERIES.benchmark)}));
    }
    const hs = NAV_SERIES[highlight];
    if (hs) {
      svg.appendChild(sv("path", {class:"ln-hi", d:path(hs)}));
      const last = hs[hs.length - 1];
      svg.appendChild(sv("circle", {class:"dot", cx:x(n - 1), cy:y(last), r:3.2}));
      if (!narrow) {
        const lab = sv("text", {class:"hi", x:x(n - 1) + 8, y:y(last) + 4});
        lab.textContent = usd0.format(last);
        svg.appendChild(lab);
      }
    }

    const t1 = sv("text", {x:padL, y:h - 8});
    t1.textContent = shortDate(NAV_DATES[0]);
    const t2 = sv("text", {x:w - padR, y:h - 8, "text-anchor":"end"});
    t2.textContent = shortDate(NAV_DATES[n - 1]);
    svg.appendChild(t1);
    svg.appendChild(t2);

    host.appendChild(svg);

    const st = byKey(highlight);
    if (st) {
      $("#chart-caption").textContent = "Heavy line: " + st.name + ", " + usd2.format(st.nav) + " (" +
        pct(st.return_pct) + "). Dashed line: the buy-and-hold benchmark. Faint lines: the other books. " +
        "From " + (NAV_DATES.length ? shortDate(NAV_DATES[0]) : "the first day") +
        " to " + (NAV_DATES.length ? shortDate(NAV_DATES[NAV_DATES.length - 1]) : "today") +
        ", one point per weekday.";
    }
  }

  function buildPicker() {
    const host = $("#chart-picker");
    host.textContent = "";
    STANDINGS.forEach(function (r) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = r.is_benchmark ? "bench" : "";
      b.textContent = r.is_benchmark ? "Buy and hold" : r.name.split(" ").slice(-1)[0];
      b.setAttribute("aria-pressed", r.advisor === highlight ? "true" : "false");
      b.addEventListener("click", function () {
        highlight = r.advisor;
        Array.prototype.forEach.call(host.children, function (c) { c.setAttribute("aria-pressed", "false"); });
        b.setAttribute("aria-pressed", "true");
        drawChart();
      });
      host.appendChild(b);
    });
  }

  /* ---------------- today ---------------- */

  const GENERIC_HOLD = "the advisor sent no orders";
  const OUTCOMES = {
    chose_to_hold:{cls:"o-hold", glyph:"tpl-glyph-hold", text:"Held by choice \u2014 no orders placed"},
    all_rejected:{cls:"o-rejected", glyph:"tpl-glyph-refused", text:"Every order refused \u2014 book unchanged"},
    unreachable:{cls:"o-unreachable", glyph:"tpl-glyph-unreachable", text:"Advisor unreachable \u2014 no decision recorded"}
  };

  function renderOrder(o) {
    const li = tpl("tpl-order");
    const act = $(".act", li);
    act.classList.add(o.action === "buy" ? "act-buy" : "act-sell");
    act.textContent = o.action;
    $(".inst", li).textContent = o.instrument;
    $(".amt", li).textContent = usd0.format(o.amount_usd);
    $(".at", li).textContent = "at " + num.format(o.price);
    $(".reason", li).textContent = o.reason;

    const meta = $(".order-meta", li);
    const bits = [
      {k:"Conviction", v:Math.round(o.conviction * 100) + " of 100"},
      {k:"Horizon", v:o.horizon_days > 0 ? o.horizon_days + " days" : "closing out"}
    ];
    bits.forEach(function (bit) {
      const m = tpl("tpl-meta-item");
      $("b", m).textContent = bit.k;
      $(".v", m).textContent = bit.v;
      meta.appendChild(m);
    });

    if (o.considered && o.considered.length) {
      const ul = $(".considered", li);
      ul.hidden = false;
      o.considered.forEach(function (c) {
        const item = tpl("tpl-considered-item");
        $(".ci", item).textContent = c.instrument;
        $(".cw", item).textContent = "\u2014 considered, not taken: " + c.why_not;
        ul.appendChild(item);
      });
    }
    return li;
  }

  function renderToday(list) {
    const host = $("#today-list");
    host.textContent = "";
    const deck = $("#today-deck");
    if (deck && TODAY_AS_OF) { deck.textContent = "Orders, refusals and reasons \u2014 " + longDate(TODAY_AS_OF) + "."; }
    if (!list.length) { setState("today", "empty"); return; }

    list.forEach(function (d) {
      const st = byKey(d.advisor);
      const art = tpl("tpl-day");
      const link = $(".day-head h3 a", art);
      link.textContent = st ? st.name : d.advisor;
      link.setAttribute("href", bookHref(d.advisor));
      $(".pslot", art).replaceWith(portraitNode(d.advisor, st ? st.name : d.advisor, "sm"));
      $(".role", art).textContent = roleOf(d.advisor);
      $(".navline", art).textContent = "Book before today\u2019s orders: " + usd2.format(d.nav_before);
      const mini = allocBlock(d.advisor, "day");
      if (mini) { $(".day-head", art).appendChild(mini); }

      const ul = $(".orders", art);
      (d.orders || []).forEach(function (o) { ul.appendChild(renderOrder(o)); });
      if (!(d.orders || []).length) { ul.remove(); }

      if ((d.rejected || []).length) {
        const box = $(".refused", art);
        box.hidden = false;
        const rl = $("ul", box);
        d.rejected.forEach(function (r) {
          const li = tpl("tpl-li");
          li.textContent = "Refused: " + r.why;
          rl.appendChild(li);
        });
      }

      if (d.held) {
        const spec = OUTCOMES[d.held.kind];
        const box = $(".outcome", art);
        box.hidden = false;
        box.classList.add(spec.cls);
        $(".glyph", box).appendChild(svgTpl(spec.glyph));
        $(".text", box).textContent = spec.text;
        const why = d.held.why && d.held.why !== GENERIC_HOLD ? d.held.why : "";
        $("p", box).textContent = why;
        $("p", box).hidden = !why;
      }

      if (d.note) {
        const note = $(".note", art);
        note.hidden = false;
        note.textContent = d.note;
      }
      host.appendChild(art);
    });
  }

  /* ---------------- one advisor ---------------- */

  const RECORD_LABEL = {moved:"Book moved", held:"Held by choice", refused:"All orders refused", unreachable:"Unreachable"};

  function renderBook(b) {
    $("#h-advisor").textContent = b.name;
    $("#advisor-mandate").textContent = b.mandate;
    const deck = $("#advisor-deck");
    if (deck) { deck.textContent = (b.title || "Advisor") + " \u00b7 day " + b.days; }
    const slot = $("#advisor-pslot");
    if (slot) {
      const pn = portraitNode(b.advisor === "benchmark" ? "__none" : b.advisor, b.name, "lg");
      pn.id = "advisor-pslot";
      slot.replaceWith(pn);
    }

    const figs = $("#advisor-figures");
    figs.textContent = "";
    const items = [
      {k:"Net asset value", v:usd2.format(b.nav)},
      {k:"Return", node:delta(b.return_pct)},
      {k:"Cash / invested", v:usd0.format(b.cash) + " / " + usd0.format(b.invested)},
      {k:"Max drawdown", v:ddText(b.max_drawdown_pct)}
    ];
    items.forEach(function (it) {
      const dt = document.createElement("dt");
      dt.textContent = it.k;
      const dd = document.createElement("dd");
      if (it.node) { dd.appendChild(it.node); } else { dd.textContent = it.v; }
      const wrapper = document.createElement("div");
      wrapper.appendChild(dt);
      wrapper.appendChild(dd);
      figs.appendChild(wrapper);
    });

    const cap = $("#positions-caption");
    if (cap) {
      const n = b.positions.length;
      cap.textContent = n
        ? (n === 1 ? "One instrument" : n + " instruments") + " held, of a limit of twelve. Value is marked at the close."
        : "No positions. The whole book is in cash.";
    }
    const ah = $("#advisor-alloc");
    if (ah) {
      ah.textContent = "";
      const block = allocBlock(b.advisor, "book");
      if (block) { ah.appendChild(block); ah.hidden = false; } else { ah.hidden = true; }
    }
    const pb = $("#positions-body");
    pb.textContent = "";
    b.positions.forEach(function (p) {
      const tr = tpl("tpl-position-row");
      $("th", tr).textContent = p.instrument;
      $(".qty", tr).textContent = num.format(p.qty);
      $(".cost", tr).textContent = usd0.format(p.cost);
      $(".value .v", tr).textContent = usd0.format(p.value);
      if (!p.priced) {
        const tagcost = $(".atcost", tr);
        tagcost.hidden = false;
        $(".value .v", tr).classList.add("stale");
        const sr = document.createElement("span");
        sr.className = "sr";
        sr.textContent = " no price arrived today; held at cost";
        $(".value", tr).appendChild(sr);
      }
      $(".ret", tr).appendChild(delta(p.return_pct));
      pb.appendChild(tr);
    });

    const strip = $("#record-strip");
    strip.textContent = "";
    b.record.forEach(function (k, i) {
      const m = tpl("tpl-mark");
      m.classList.add("mk-" + k);
      m.setAttribute("title", "Day " + (i + 1) + " \u2014 " + RECORD_LABEL[k]);
      $(".sr", m).textContent = "Day " + (i + 1) + ": " + RECORD_LABEL[k] + ". ";
      strip.appendChild(m);
    });

    const dl = $("#decisions-list");
    dl.textContent = "";
    b.decisions.forEach(function (d) {
      const li = tpl("tpl-decision");
      $(".when", li).textContent = shortDate(d.date) + " 2026";
      $("p", li).textContent = d.text;
      dl.appendChild(li);
    });
  }

  /* Switch books in place; the address keeps up so a book can be linked to. */
  function bookPicker(books, current) {
    const host = $("#book-picker");
    if (!host) { return; }
    host.textContent = "";
    const order = STANDINGS.map(function (r) { return r.advisor; })
      .filter(function (k) { return Object.prototype.hasOwnProperty.call(books, k); });
    order.forEach(function (k) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = k === "benchmark" ? "bench" : "";
      b.textContent = k === "benchmark" ? "Buy and hold" : books[k].name.split(" ").slice(-1)[0];
      b.setAttribute("aria-pressed", k === current ? "true" : "false");
      b.addEventListener("click", function () {
        renderBook(books[k]);
        Array.prototype.forEach.call(host.children, function (c) { c.setAttribute("aria-pressed", "false"); });
        b.setAttribute("aria-pressed", "true");
        if (window.history && window.history.replaceState) {
          window.history.replaceState(null, "", "?a=" + encodeURIComponent(k) + "#advisor");
        }
      });
      host.appendChild(b);
    });
  }

  /* ---------------- the desk ---------------- */

  function renderRoster(r) {
    const a = $("#roster-advisors");
    const s = $("#roster-staff");
    a.textContent = "";
    s.textContent = "";
    r.advisors.forEach(function (p) {
      const node = tpl("tpl-person");
      const pn = portraitNode(p.advisor, p.name, "lg");
      const slot = $(".pslot", node);
      slot.replaceWith(pn);
      if (PORTRAITS[p.advisor] && PORTRAITS[p.advisor].sample) {
        const cap = document.createElement("span");
        cap.className = "pcap";
        cap.textContent = "Portrait treatment \u2014 sample";
        pn.after(cap);
      }
      const link = $("h3 a", node);
      link.textContent = p.name;
      link.setAttribute("href", "desk.html?a=" + p.advisor);
      $(".desk-role", node).textContent = p.role;
      $(".mandate", node).textContent = p.mandate;
      $(".char", node).textContent = p.character;
      const block = allocBlock(p.advisor, "card");
      if (block) { node.appendChild(block); }
      a.appendChild(node);
    });
    r.staff.forEach(function (p) {
      const node = tpl("tpl-person");
      $(".pslot", node).replaceWith(portraitNode(p.key, p.name, "lg"));
      const h3 = $("h3", node);
      h3.textContent = p.name;
      $(".desk-role", node).textContent = p.role;
      $(".mandate", node).textContent = p.mandate;
      $(".char", node).textContent = p.character;
      s.appendChild(node);
    });
  }

  /* The desk's own writing, shown only when it exists. A page that prints a
     placeholder quotation from an evaluator who has not written one yet is
     publishing a fact nobody stated, which is the one failure this record cannot
     survive — so the whole block stays hidden instead. */
  function renderWriting(d) {
    const host = $("#writing");
    if (!host) { return; }
    let shown = false;
    [["review", d.review], ["letter", d.letter]].forEach(function (pair) {
      const when = $("#" + pair[0] + "-when");
      const text = $("#" + pair[0] + "-text");
      const head = $("#" + pair[0] + "-head");
      if (!when || !text) { return; }
      const note = pair[1];
      if (note && note.text) {
        when.textContent = shortDate(note.date);
        text.textContent = note.text;
        shown = true;
      } else {
        when.textContent = "";
        text.textContent = "";
        when.hidden = true;
        text.hidden = true;
        if (head) { head.hidden = true; }
      }
    });
    const rw = $("#rewrite");
    const rwd = d.rewrite;
    if (rw) {
      if (rwd && (rwd.changed || rwd.why)) {
        $("#rewrite-when").textContent = longDate(rwd.date) + " \u00b7 " + rwd.name +
          (rwd.title ? ", " + rwd.title.replace(/^Advisor,\s*/, "").toLowerCase() : "");
        $("#rewrite-changed").textContent = rwd.changed;
        $("#rewrite-why").textContent = rwd.why;
        rw.hidden = false;
        shown = true;
      } else {
        rw.hidden = true;
      }
    }
    host.hidden = !shown;
  }

  /* ---------------- the log ---------------- */

  function renderLog(rows) {
    const host = $("#log-list");
    if (!host) { return; }
    host.textContent = "";
    rows.forEach(function (row) {
      const node = tpl("tpl-logrow");
      $(".logdate", node).textContent = shortDate(row.date || "");
      $(".logtext", node).textContent = row.message || "";
      host.appendChild(node);
    });
  }

  /* ---------------- states, loading, wiring ---------------- */

  function setState(view, state) {
    const sec = document.querySelector('[data-view="' + view + '"]');
    if (sec) { sec.setAttribute("data-state", state); }
  }

  function have(view) {
    return !!document.querySelector('[data-view="' + view + '"]');
  }

  /* Every view survives a missing or malformed file: it falls back to its
     designed empty state, and one bad file never blanks the others. */
  function load(url, fallback) {
    return fetch(url, {cache: "no-store"}).then(function (res) {
      if (!res.ok) { throw new Error(String(res.status)); }
      return res.json();
    }).catch(function () { return fallback; });
  }

  /* Which book the advisor view opens on: ?a=<id> if it names one the desk
     published, otherwise whoever is leading. Never an id from the address bar
     that the data does not contain. */
  function wantedBook(books) {
    const keys = Object.keys(books || {});
    if (!keys.length) { return null; }
    const asked = new URLSearchParams(window.location.search).get("a");
    if (asked && Object.prototype.hasOwnProperty.call(books, asked)) { return asked; }
    const leader = STANDINGS.filter(function (r) { return !r.is_benchmark; })[0];
    if (leader && Object.prototype.hasOwnProperty.call(books, leader.advisor)) {
      return leader.advisor;
    }
    return keys[0];
  }

  /* Silence has to be visible.
     Left alone, this desk fails politely: the shift stops, or a provider starts
     refusing, and the last good page keeps serving with a date nobody reads. So
     the masthead says how old the record is in days, and says out loud when the
     feed could not see most of the market. Both are computed in the browser
     against today, because a stale file cannot report its own staleness. */
  function ageInDays(iso) {
    const then = Date.parse(iso + "T00:00:00Z");
    if (!then) { return null; }
    return Math.floor((Date.now() - then) / 86400000);
  }

  function renderHealth(as_of, feed) {
    const host = $("#health");
    if (!host) { return; }
    const notes = [];
    const age = as_of ? ageInDays(as_of) : null;
    if (age !== null && age >= 4) {
      notes.push("The last close marked here is " + age + " days old. The desk runs " +
                 "every weekday, so this page is not current.");
    }
    if (feed && feed.universe && feed.covered < feed.universe) {
      const missed = feed.universe - feed.covered;
      notes.push(missed + " of " + feed.universe + " instruments could not be priced " +
                 "on that day and are held at cost" +
                 (feed.short && feed.short.length ? " (" + feed.short.join(", ") + ")" : "") +
                 ".");
    }
    if (!notes.length) { host.hidden = true; return; }
    host.textContent = "";
    notes.forEach(function (line) {
      const p = document.createElement("p");
      p.textContent = line;
      host.appendChild(p);
    });
    host.hidden = false;
  }

  function stamp(as_of, day) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-asof]"), function (el) {
      el.textContent = as_of ? shortDate(as_of) : "\u2014";
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-day]"), function (el) {
      el.textContent = day ? String(day) : "\u2014";
    });
  }

  function boot() {
    const views = ["standings", "today", "advisor", "staff", "log"];
    views.forEach(function (v) { if (have(v)) { setState(v, "loading"); } });

    Promise.all([
      load("data/view-standings.json", null),
      load("data/view-today.json", null),
      load("data/view-advisor.json", null),
      load("data/view-desk.json", null),
      load("data/changelog.json", null)
    ]).then(function (out) {
      const s = out[0], t = out[1], a = out[2], d = out[3], log = out[4];

      if (s) {
        STANDINGS = s.rows || [];
        NAV_DATES = s.dates || [];
        NAV_SERIES = s.series || {};
        HOLDS = s.holds || {};
        RECORD = s.record || {};
        ALLOC = s.alloc || {};
        INSTR = s.instruments || {};
        SWEEP = s.sweep && typeof s.sweep.pct === "number" ? s.sweep : null;
        stamp(s.as_of, s.day);
        renderHealth(s.as_of, s.feed);
      }
      if (d) {
        ROSTER = {advisors: d.advisors || [], staff: d.staff || []};
        PORTRAITS = d.portraits || {};
      }
      if (t) { TODAY = t.entries || []; TODAY_AS_OF = t.as_of || ""; }

      if (have("standings")) {
        if (STANDINGS.length) {
          renderLeader(STANDINGS);
          renderSummary(STANDINGS);
          renderStandings(STANDINGS);
          buildPicker();
          /* ready first: a chart drawn into a hidden container measures 0px wide */
          setState("standings", "ready");
          drawChart();
        } else { setState("standings", "empty"); }
      }

      if (have("today")) {
        if (TODAY.length) { renderToday(TODAY); setState("today", "ready"); }
        else { setState("today", "empty"); }
      }

      if (have("advisor")) {
        const books = (a && a.books) || {};
        const key = wantedBook(books);
        BOOK = key ? books[key] : null;
        if (BOOK && BOOK.positions) {
          renderBook(BOOK);
          bookPicker(books, key);
          setState("advisor", "ready");
        }
        else { setState("advisor", "empty"); }
      }

      if (have("staff")) {
        if (ROSTER.advisors.length) {
          renderRoster(ROSTER);
          renderWriting(d || {});
          setState("staff", "ready");
        } else { setState("staff", "empty"); }
      }

      if (have("log")) {
        const rows = Array.isArray(log) ? log : [];
        if (rows.length) { renderLog(rows); setState("log", "ready"); }
        else { setState("log", "empty"); }
      }
    });
  }

  let t = null;
  window.addEventListener("resize", function () {
    window.clearTimeout(t);
    t = window.setTimeout(drawChart, 140);
  });

  boot();
})();
