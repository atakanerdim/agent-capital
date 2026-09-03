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

  function todayLine(key) {
    if (key === "benchmark") {
      return "Nothing. This book has never placed an order and never will \u2014 that is the point of it.";
    }
    const d = TODAY.filter(function (t) { return t.advisor === key; })[0];
    if (!d) { return "No entry published for today."; }
    if (d.held) { return OUTCOMES[d.held.kind].text + ". " + d.held.why; }
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
    const bench = byKey("benchmark");
    const gap = bench ? r.return_pct - bench.return_pct : 0;
    $(".sparknote", row).textContent = usd2.format(r.nav) + " today, " + pct(r.return_pct) +
      " since the open. Against buy and hold: " + pct(gap) + ". Deepest fall from a peak \u2212" +
      r.max_drawdown_pct.toFixed(2) + "%.";

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
      chips.textContent = "All 27 instruments, equally weighted, untouched since 7 August.";
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
      link.setAttribute("href", "#advisor");
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
      $(".c-dd", tr).appendChild(document.createTextNode("\u2212" + r.max_drawdown_pct.toFixed(2) + "%"));
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
    const padL = 46, padR = narrow ? 14 : 74, padT = 14, padB = 26;

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

    /* the opening $100,000 */
    if (100000 > lo && 100000 < hi) {
      svg.appendChild(sv("line", {class:"base", x1:padL, y1:y(100000), x2:w - padR, y2:y(100000)}));
      const bl = sv("text", {x:padL - 6, y:y(100000) + 3.5, "text-anchor":"end"});
      bl.textContent = "100k";
      svg.appendChild(bl);
    }
    [hi - span * 0.03, lo + span * 0.03].forEach(function (v) {
      const t = sv("text", {x:padL - 6, y:y(v) + 3.5, "text-anchor":"end"});
      t.textContent = Math.round(v / 1000) + "k";
      svg.appendChild(t);
    });

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
    if (!list.length) { setState("today", "empty"); return; }

    list.forEach(function (d) {
      const st = byKey(d.advisor);
      const art = tpl("tpl-day");
      const link = $(".day-head h3 a", art);
      link.textContent = st ? st.name : d.advisor;
      $(".pslot", art).replaceWith(portraitNode(d.advisor, st ? st.name : d.advisor, "sm"));
      $(".role", art).textContent = roleOf(d.advisor);
      $(".navline", art).textContent = "Opened at " + usd2.format(d.nav_before);

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
        $("p", box).textContent = d.held.why;
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
      const pn = portraitNode(b.advisor, b.name, "lg");
      pn.style.flex = "none";
      pn.style.width = "130px";
      slot.replaceWith(pn);
    }

    const figs = $("#advisor-figures");
    figs.textContent = "";
    const items = [
      {k:"Net asset value", v:usd2.format(b.nav)},
      {k:"Return", node:delta(b.return_pct)},
      {k:"Cash / invested", v:usd0.format(b.cash) + " / " + usd0.format(b.invested)},
      {k:"Max drawdown", v:"\u2212" + b.max_drawdown_pct.toFixed(2) + "%"}
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
        stamp(s.as_of, s.day);
        renderHealth(s.as_of, s.feed);
      }
      if (d) {
        ROSTER = {advisors: d.advisors || [], staff: d.staff || []};
        PORTRAITS = d.portraits || {};
      }
      if (t) { TODAY = t.entries || []; }

      if (have("standings")) {
        if (STANDINGS.length) {
          renderLeader(STANDINGS);
          renderSummary(STANDINGS);
          renderStandings(STANDINGS);
          buildPicker();
          drawChart();
          setState("standings", "ready");
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
        if (BOOK && BOOK.positions) { renderBook(BOOK); setState("advisor", "ready"); }
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
