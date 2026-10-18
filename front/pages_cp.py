"""Crestpoint page makers.

Each maker takes the design's template and the desk's records and returns (template, live).
Replacements are exact: if the design text a replacement expects is not there, the build
stops instead of publishing a page with stale numbers in it. F is firm.py's namespace.
"""
import datetime as dt, html, re

DESK = {'momentum': (377, 'top'), 'value': (433, 'top'), 'macro': (489, 'top'), 'careful': (545, 'top'),
        'contrarian': (377, 'bot'), 'fx': (433, 'bot'), 'metals': (489, 'bot'), 'index': (545, 'bot')}
CABINET = {'momentum': 1011, 'value': 1037, 'macro': 1063, 'careful': 1089, 'contrarian': 1115, 'fx': 1141,
           'metals': 1167, 'index': 1193}
ROLE = {'momentum': 'momentum', 'value': 'value', 'macro': 'macro', 'careful': 'capital preservation',
        'contrarian': 'contrarian', 'fx': 'currencies', 'metals': 'precious metals', 'index': 'index'}
ROSTER_NAME = {}   # filled from the roster


# The site prints no betting vocabulary, even figuratively ("the safest bet"). An agent's
# line that uses it is not edited: it is left out, and the page says so.
BANNED = re.compile(r'\b(bet|bets|betting|odds|wager|wagers|punter|bookmaker)\b', re.I)
WITHHELD = 'Not shown: it uses betting vocabulary, which this site does not print.'


def clean(text, quote=False):
    if text and BANNED.search(text):
        return WITHHELD
    return ('\u201c%s\u201d' % text) if (quote and text) else text


def e(s):
    return html.escape(str(s), quote=True)


def money(v):
    return '${:,.0f}'.format(v)


def order_text(action, instrument, amount):
    return '%s %s, %s' % (action.capitalize(), instrument, money(amount))


def weekday(iso):
    return dt.date.fromisoformat(iso).weekday()


# ---------------------------------------------------------------- shared pieces
def script_dates_nav(F, t, w):
    t = F.resub(t, r"var DATES = \[[^\]]*\];", "var LIVE = window.LIVE;\nvar DATES = LIVE.dates;\nvar NL = DATES.length - 1;", 1, w)
    t = F.resub(t, r"var CASH = \[[^\]]*\];\n", "", 1, w) if 'var CASH = [' in t else t
    t = F.resub(t, r"var NAV = \{.*?\n\};", "var NAV = LIVE.nav;", 1, w)
    return t


def chart_markup(F, t, w):
    """Gridlines and ticks of a return chart become lists computed by the publishing step."""
    i = t.index('<line class="gl" x1="70" x2="800" y1="20" y2="20"></line>')
    j = t.index('<g clip-path', i)
    t = t[:i] + ('<sc-for list="{{ L.chart.grid }}" as="g"><line class="{{ g.cls }}" x1="70" x2="800" '
                 'y1="{{ g.y }}" y2="{{ g.y }}"></line></sc-for>\n') + t[j:]
    t = F.resub(t, r'(<span class="yt" style="top: [\d.]+%">[^<]*</span>\s*)+',
                '<sc-for list="{{ L.chart.yt }}" as="y"><span class="yt" style="top: {{ y.t }}%">{{ y.l }}</span></sc-for>\n',
                1, w)
    t = F.resub(t, r'(<span class="xt[^"]*" style="left: [\d.]+%">[^<]*</span>\s*)+',
                '<sc-for list="{{ L.chart.xt }}" as="x"><span class="{{ x.cls }}" style="left: {{ x.l }}%">{{ x.t }}</span></sc-for>\n',
                1, w)
    return t


def chart_live(F, R, RC, CH):
    ch = dict(CH)
    cash = [b['k'] for b in RC['books'] if b['never']]
    if cash:
        last = (R['nav'][cash[0]][-1] / 100000 - 1) * 100
        y = 20 + (CH['top'] - last) / CH['range'] * 336
        ch['flat'], ch['flatTop'] = True, round(y / 400 * 100 - 6.5, 1)
    else:
        ch['flat'], ch['flatTop'] = False, 0
    bits = ['%s %s%s' % (b['name'].split()[0], F.pct(b['ret']), ', all in cash' if b['never'] else '')
            for b in sorted(RC['books'], key=lambda b: -b['ret'])]
    ch['aria'] = ('Line chart of returns from %s to %s for eight advisors and Buy and hold, the ghost. On %s: %s; '
                  'the ghost %s.' % (F.D(R['dates'][0]), F.D(R['asof']), F.D(R['asof'], False), '; '.join(bits),
                                     F.pct(R['g_ret'])))
    return ch


def refusal_live(F, R, r):
    return {'when': '%s%s' % (F.D(r['date']), (', %s UTC' % r['utc']) if r['utc'] else ''),
            'date': F.D(r['date']), 'name': R['rows'][r['adv']]['name'], 'role': ROLE[r['adv']],
            'adv': r['adv'], 'img': 'assets/portraits/crestpoint/%s.svg' % r['adv'],
            'order': order_text(r['action'], r['instrument'], r['amount']), 'why': r['why']}


def notes(R):
    """Each advisor's latest note with the orders, and its date."""
    out = {}
    for day in sorted(R['orders'], reverse=True):
        for a, x in R['orders'][day].items():
            if a not in out and (x.get('note') or '').strip():
                out[a] = {'text': clean(x['note'].strip(), True), 'date': day}
    return out


def verdict_live(F, R, RC):
    return {'h': RC['verdict']['h'], 'p': RC['verdict']['p'], 'under': RC['verdict']['under'],
            'desk': F.pct(R['desk_ret']), 'ghost': F.pct(R['g_ret'])}


def books_meta(F, R):
    out = {}
    for k, r in R['rows'].items():
        avg, last = R['inv'][k]
        out[k] = {'invL': F.pct1(last), 'invA': F.pct1(avg), 'mandate': r['mandate'], 'name': r['name']}
    return out


# ---------------------------------------------------------------- Home
def hero(F, R, t, w):
    """The engraved floor: who is on shift on the last trading day, and that day's orders."""
    asof = R['asof']
    wd = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][weekday(asof)]
    names = {r['ad']: r['id'] for r in R['roster']}

    def desk(m):
        g, title = m.group(0), m.group(2)
        who = next((i for n, i in names.items() if title.startswith(n)), None)
        if who is None:
            raise SystemExit('%s: no roster entry for desk %r' % (w, title))
        on = wd in R['days_by'][who]
        dk = re.search(r'<rect class="dk" pathLength="1" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"></rect>', g)
        tx = re.search(r'<text class="ini[^"]*" x="([\d.]+)" y="([\d.]+)">([A-Z]{2})</text>', g)
        ch = re.search(r'<circle class="ch"[^>]*></circle>', g).group(0)
        x, y, wdt, hgt = dk.groups()
        k = re.search(r'--k: (\d+)', g).group(1)
        rect = '<rect class="dk" pathLength="1" x="%s" y="%s" width="%s" height="%s"></rect>' % (x, y, wdt, hgt)
        if on:
            desk.j += 1
            return ('<g class="desk on" style="--k: %s; --j: %d"><title>%s</title>%s<rect class="lit" x="%s" y="%s" '
                    'width="%s" height="%s"></rect>%s<text class="ini ini-w" x="%s" y="%s">%s</text><text class="ini ini-d" '
                    'x="%s" y="%s">%s</text></g>' % (k, desk.j - 1, title, rect, x, y, wdt, hgt, ch,
                                                     tx.group(1), tx.group(2), tx.group(3), tx.group(1), tx.group(2), tx.group(3)))
        return ('<g class="desk" style="--k: %s"><title>%s</title>%s%s<text class="ini" x="%s" y="%s">%s</text></g>'
                % (k, title, rect, ch, tx.group(1), tx.group(2), tx.group(3)))
    desk.j = 0
    t = F.resub(t, r'<g class="desk( on)?" style="[^"]*"><title>([^<]*)</title>.*?</g>', desk, 11, w)

    day = R['orders'][asof]
    filled = [(a, o) for a in DESK for o in (day.get(a, {}).get('orders') or [])]
    refused = [(a, r) for a in DESK for r in (day.get(a, {}).get('rejected') or [])]
    marks = []

    def lane(a):
        x, row = DESK[a]
        return ('M%d 119 L%d 112 L740 112 L740 158' % (x, x)) if row == 'top' else ('M%d 197 L%d 206 L740 206 L740 158' % (x, x))
    when = F.D(asof)
    if filled:
        a, o = filled[0]
        name = R['rows'][a]['name']
        marks.append('<circle class="mk" r="4.5" style="offset-path: path(\'%s L%d 158 L%d 176\'); --dl: 2400ms"><title>%s %ss %s, %s. Filled, %s</title></circle>'
                     % (lane(a), CABINET[a], CABINET[a], e(name), o['action'], o['instrument'], money(o['amount_usd']), when))
    if refused:
        a, r = refused[0]
        name = R['rows'][a]['name']
        o = r['order']
        marks.append('<circle class="mk mk-b" r="4.5" style="offset-path: path(\'%s L796 158\'); --dl: 2750ms"><title>%s %ss %s, %s. Refused, %s</title></circle>'
                     % (lane(a), e(name), o['action'], o['instrument'], money(o.get('amount_usd', 0)), when))
        marks.append('<g class="rxg"><title>Refused by the risk code, %s</title><path class="rx" d="M782 151 L794 165 M794 151 L782 165"></path></g>' % when)
    marks.append('<circle class="mk" r="4.5" style="offset-path: path(\'M611 184 L611 236 L584 236 L584 416\'); --dl: 3300ms"><title>Rafael Costa marks every book and republishes the standings, %s</title></circle>' % when)
    t = F.resub(t, r'<circle class="mk" r="4\.5".*?Rafael Costa marks every book[^<]*</title></circle>', '\n'.join(marks), 1, w)

    nf, nr = len(filled), len(refused)
    story = 'The day’s orders travel to the risk code'
    if nf and nr:
        story += ': %s %s to the ledger and %s %s refused.' % (F.word(nf), 'passes' if nf == 1 else 'pass', F.word(nr), 'is' if nr == 1 else 'are')
    elif nf:
        story += ' and %s to the ledger.' % ('it passes' if nf == 1 else 'all %s pass' % F.word(nf))
    elif nr:
        story += ' and %s refused.' % ('one is' if nr == 1 else '%s are' % F.word(nr))
    else:
        story = 'Nobody sent an order that day.'
    t = F.sub(t, 'Yesterday’s orders travel to the risk code: one passes to the ledger and one is refused.', story, 1, w)
    t = F.sub(t, 'On shift today, Tue 13 Oct 2026', 'On shift, %s %s' % (F.WD[weekday(asof)], F.D(asof)), 1, w)
    t = F.sub(t, 'An order or a change, 12 Oct 2026', 'An order or a change, %s' % F.D(asof), 1, w)
    t = F.sub(t, '<p class="serial"><span>Trading day 24</span><small>12 Oct 2026</small></p>',
              '<p class="serial"><span>Trading day {{ L.day }}</span><small>{{ L.asof }}</small></p>', 1, w)
    return t


def home(F, R, RC, CH, C):
    w = 'index'
    t = F.tpl('index.dc.html')
    t = hero(F, R, t, w)
    # --- logic
    t = script_dates_nav(F, t, w)
    t = F.resub(t, r"var NOTES = \{.*?\};\n", "var NOTES = LIVE.notes;\n", 1, w)
    t = F.resub(t, r"var REASON = '[^']*';", "ADV.forEach(function (a) { var b = LIVE.books[a.nav || a.k]; if (b) { a.invL = b.invL; a.invA = b.invA; a.mandate = b.mandate; } });\nvar REASON = LIVE.refusal ? LIVE.refusal.why : '';", 1, w)
    for old, new in [('* 730 / 23', '* 730 / NL'), ('/ 730) * 23)', '/ 730) * NL)'), ('dayI: 23 })', 'dayI: NL })'),
                     ('st.dayI = 23;', 'st.dayI = NL;'), ('Math.min(23,', 'Math.min(NL,'), ('if (i >= 23)', 'if (i >= NL)')]:
        t = F.sub(t, old, new, 1, w)
    t = F.sub(t, 'yP(v) { return 20 + (1 - v) / 4.25 * 336; }', 'yP(v) { return 20 + (LIVE.chart.top - v) / LIVE.chart.range * 336; }', 1, w)
    t = F.sub(t, "last: a.ghost ? 'Hasn’t made a decision since 9 September.' : '“' + NOTES[a.k] + '”',",
              "last: a.ghost ? 'Hasn’t made a decision since 9 September.' : (NOTES[a.k] ? NOTES[a.k].text : 'No note yet.'),", 1, w)
    t = F.sub(t, "lastWhen: a.ghost ? '' : 'Note with the orders, 12 Oct 2026. Agent writing.',",
              "lastWhen: a.ghost || !NOTES[a.k] ? '' : 'Note with the orders, ' + NOTES[a.k].when + '. Agent writing.',", 1, w)
    t = F.resub(t, r"chartAria: '[^']*' \+ c\.date \+ '\.',", "chartAria: LIVE.chart.aria + ' Showing ' + c.date + '.',", 1, w)
    t = F.sub(t, "rev: a.k === 'index'", "rev: a.k === LIVE.rewrite.advisor", 1, w)
    # --- markup
    t = F.sub(t, 'the same instruments, 35 of them since 11 September,', 'the same instruments, {{ L.instruments }} of them since 11 September,', 1, w)
    t = F.sub(t, 'Rewritten 4 Oct 2026</span>', 'Rewritten {{ L.rewrite.date }}</span>', 1, w)
    t = chart_markup(F, t, w)
    t = F.sub(t, '<span class="flat-note">Cash only so far, earning the Treasury bill rate.</span>',
              '<sc-if value="{{ L.chart.flat }}"><span class="flat-note" style="top: {{ L.chart.flatTop }}%">Cash only so far, earning the Treasury bill rate.</span></sc-if>', 1, w)
    t = F.resub(t, r'<p class="state-top">[^<]*</p>\s*<p class="state-sub">[^<]*</p>\s*</div>\s*<span class="asof">As of 12 Oct 2026</span>',
                '<p class="state-top">{{ L.verdict.h }}</p>\n<p class="state-sub">{{ L.verdict.p }}</p>\n</div>\n<span class="asof">As of {{ L.asof }}</span>', 1, w)
    t = F.sub(t, '<span class="card-r">on 12 Oct 2026</span>', '<span class="card-r">on {{ L.asof }}</span>', 1, w)
    t = F.sub(t, 'type="range" min="0" max="23"', 'type="range" min="0" max="{{ L.chart.n }}"', 1, w)
    t = F.resub(t, r'<p>The desk: <b class="num">[^<]*</b> since 9 Sep\. The ghost: <b class="num">[^<]*</b>\.[^<]*</p>',
                '<p>The desk: <b class="num">{{ L.verdict.desk }}</b> since 9 Sep. The ghost: <b class="num">{{ L.verdict.ghost }}</b>. {{ L.verdict.under }}</p>', 1, w)
    # refusal
    t = F.sub(t, '<span class="asof">12 Oct 2026, 15:44 UTC</span>', '<span class="asof">{{ L.refusal.when }}</span>', 1, w)
    t = F.sub(t, '<img class="pt" src="assets/portraits/crestpoint/contrarian.svg" width="52" height="52" alt=""><p><b>Ines Kovac, contrarian.</b> Buy TLT, $5,000.</p>',
              '<img class="pt" src="{{ L.refusal.img }}" width="52" height="52" alt=""><p><b>{{ L.refusal.name }}, {{ L.refusal.role }}.</b> {{ L.refusal.order }}.</p>', 1, w)
    t = F.resub(t, r'<p class="reason"><span class="sr">[^<]*</span>', '<p class="reason"><span class="sr">{{ L.refusal.why }}</span>', 1, w)
    # rewrite: the 4 October story stays; a newer rewrite is announced with its record
    ev = R['ev']
    if ev.get('last_run') and ev['last_run'] != '2026-10-04':
        who = R['rows'].get(ev.get('advisor'), {}).get('name', ev.get('advisor'))
        t = F.sub(t, '<p><a href="how-it-runs.html#rewrite">Read the rewrite</a></p>',
                  '<p><a href="how-it-runs.html#rewrite">Read the rewrite</a></p>\n<p class="body">The latest rewrite was on %s: %s’s brief. <a href="https://github.com/atakanerdim/agent-capital/tree/main/company/evolution">Read the record</a>.</p>' % (F.D(ev['last_run']), e(who)), 1, w)
    # buttons and the neighbour
    t = F.sub(t, '<a class="btn btn-primary" href="https://atakanerdim.github.io/agent-capital/console/">Open the live desk</a>',
              '<a class="btn btn-primary" href="books.html">Open the books</a>', 1, w)
    t = F.sub(t, '<span class="door-fig num">200 matches scored</span><span class="asof">As of 12 Oct 2026</span>',
              '<span class="door-fig num">{{ L.next.headline }}</span><sc-if value="{{ L.next.asof }}"><span class="asof">{{ L.next.asof }}</span></sc-if>', 1, w)

    n = notes(R)
    live = dict(C)
    rf = R['refusals'][-1] if R['refusals'] else None
    live.update({
        'dates': R['dates'], 'nav': R['nav'], 'chart': chart_live(F, R, RC, CH), 'verdict': verdict_live(F, R, RC),
        'notes': {a: {'text': x['text'], 'when': F.D(x['date'])} for a, x in n.items()},
        'books': books_meta(F, R), 'refusal': refusal_live(F, R, rf) if rf else None,
        'instruments': R['vs']['feed']['universe'],
        'rewrite': {'advisor': R['ev'].get('advisor', 'index'), 'date': F.D(R['ev'].get('last_run', '2026-10-04'))},
    })
    if rf is None:
        raise SystemExit('index: the refusal section needs at least one refused order on record')
    return t, live


# ---------------------------------------------------------------- Proof
def series_groups(F, R, RC):
    """Books with identical histories (the cash-only ones) are drawn as one line, as the design does."""
    groups, seen = [], {}
    for b in sorted(RC['books'], key=lambda b: -b['ret']):
        key = tuple(R['nav'][b['k']])
        if key in seen:
            seen[key]['members'].append(b)
            continue
        g = {'k': b['k'], 'nav': b['k'], 'members': [b], 'ghost': False}
        seen[key] = g
        groups.append(g)
    out = []
    for g in groups:
        m = g['members']
        first = [x['name'].split()[0] for x in m]
        if len(m) == 1:
            out.append({'k': g['k'], 'nav': g['nav'], 'label': first[0], 'tip': m[0]['name'], 'ghost': False})
        else:
            tip = ', '.join(first[:-1]) + ' and ' + first[-1]
            label = '%s in cash' % F.word(len(m), True) if all(x['never'] for x in m) else '%s alike' % F.word(len(m), True)
            out.append({'k': 'cash' if all(x['never'] for x in m) else g['k'], 'nav': g['nav'], 'label': label, 'tip': tip, 'ghost': False})
    out.append({'k': 'ghost', 'nav': R['ghost'], 'label': 'Buy and hold (ghost)', 'tip': 'Buy and hold', 'ghost': True})
    return out


def table_rows(F, R, RC):
    g = R['rows'][R['ghost']]
    rows = []
    def vs(v):
        if abs(v) < 0.005:
            return 'level', '', ''
        return ('%.2f pp %s' % (abs(v), 'ahead' if v > 0 else 'behind'), 'ahead' if v > 0 else 'behind',
                'tri-up' if v > 0 else 'tri-dn')
    entries = [('book', b) for b in RC['books']]
    entries.append(('ghost', None))
    entries.append(('desk', None))
    # sorted by return, the ghost and the desk in their places
    def ret(en):
        return {'book': lambda: en[1]['ret'], 'ghost': lambda: g['return_pct'], 'desk': lambda: R['desk_ret']}[en[0]]()
    for kind, b in sorted(entries, key=lambda en: -ret(en)):
        if kind == 'ghost':
            rows.append({'cls': 'ghost', 'who': 'Buy and hold (ghost)', 'sub': 'every instrument, equal weight, never traded',
                         'ret': F.pct(g['return_pct']), 'mdd': '%.2f%%' % g['max_drawdown_pct'],
                         'inv': F.pct1(R['inv'][R['ghost']][0]), 'vs': '—', 'vsCls': '', 'tri': ''})
        elif kind == 'desk':
            t, c, tri = vs(R['desk_ret'] - g['return_pct'])
            rows.append({'cls': 'desk', 'who': 'The desk', 'sub': 'equal weight of the eight', 'ret': F.pct(R['desk_ret']),
                         'mdd': '%.2f%%' % RC['desk_mdd'], 'inv': '—', 'vs': t, 'vsCls': c, 'tri': tri})
        else:
            t, c, tri = vs(b['vs'])
            inv = b['avg_inv']
            rows.append({'cls': '', 'who': b['name'], 'sub': SHORT[b['k']], 'ret': F.pct(b['ret']), 'mdd': '%.2f%%' % b['mdd'],
                         'inv': '0%' if inv == 0 else F.pct1(inv), 'vs': t, 'vsCls': c, 'tri': tri})
    return rows


SHORT = {'momentum': 'momentum', 'value': 'value', 'macro': 'macro', 'careful': 'careful', 'contrarian': 'contrarian',
         'fx': 'currencies', 'metals': 'metals', 'index': 'index'}


def gates_live(F, R, RC):
    N = len(R['dates'])
    out = []
    G = {g['k']: g for g in RC['gates']}
    def st(o):
        return ('open', 'Open') if o else ('', 'Closed')
    c, s = st(G['g1']['open'])
    out.append({'name': 'Long enough', 'pre': '', 'num': str(N), 'post': ' of %d trading days' % F.GATE_DAYS,
                'off': 0 if G['g1']['open'] else round(1 - N / F.GATE_DAYS, 3), 'lock': True, 'record': False, 'cls': c, 'state': s})
    c, s = st(G['g2']['open'])
    out.append({'name': 'The desk is ahead', 'pre': 'Desk ', 'num': F.pct(R['desk_ret']), 'post': ', ghost %s' % F.pct(R['g_ret']),
                'off': 0 if G['g2']['open'] else 1, 'lock': True, 'record': False, 'cls': c, 'state': s})
    c, s = st(G['g3']['open'])
    out.append({'name': 'Most advisors are ahead', 'pre': '', 'num': str(len(RC['counted'])),
                'post': ' of 8 ahead while invested, %d needed' % F.GATE_BREADTH,
                'off': 0 if G['g3']['open'] else round(1 - len(RC['counted']) / F.GATE_BREADTH, 3), 'lock': True, 'record': False, 'cls': c, 'state': s})
    c, s = st(G['g3']['open'])
    out.append({'name': 'Ahead while invested', 'pre': '', 'num': '', 'post': 'Only advisors at least half invested count',
                'off': 0 if G['g3']['open'] else 1, 'lock': True, 'record': False, 'cls': c, 'state': s})
    dm, gm = RC['desk_mdd'], RC['g_mdd']
    top = max(2.5, dm, gm) * 1.1
    out.append({'name': 'Risk, for the record', 'pre': 'Desk’s worst drop ', 'num': '%.2f%%' % dm, 'post': ', ghost’s %.2f%%' % gm,
                'lock': False, 'record': True, 'cls': 'record', 'state': '',
                'dy': round(96 - dm / top * 80, 1), 'dh': round(dm / top * 80, 1), 'gy': round(96 - gm / top * 80, 1), 'gh': round(gm / top * 80, 1)})
    return out


def proof(F, R, RC, CH, C):
    w = 'proof'
    t = F.tpl('proof.dc.html')
    t = script_dates_nav(F, t, w)
    t = F.resub(t, r"var SERIES = \[.*?\n\];", "var SERIES = LIVE.series;", 1, w)
    for old, new in [('/ 730) * 23)', '/ 730) * NL)'), ('* 730 / 23', '* 730 / NL'), ("deskI: still ? 23 : 0", "deskI: still ? NL : 0"),
                     ("this.setState({ deskI: 23, studioI: 5,", "this.setState({ deskI: NL, studioI: 5,"),
                     ("this.setState({ mode: 'still', deskI: 23,", "this.setState({ mode: 'still', deskI: NL,"),
                     ("Math.min(23, Math.floor((performance.now() - t0) / 95))", "Math.min(NL, Math.floor((performance.now() - t0) / 95))"),
                     ("if (i >= 23) self.stop('d');", "if (i >= NL) self.stop('d');")]:
        t = F.sub(t, old, new, 1, w)
    t = F.sub(t, 'yP(v) { return 20 + (1 - v) / 4.25 * 336; }', 'yP(v) { return 20 + (LIVE.chart.top - v) / LIVE.chart.range * 336; }', 1, w)
    t = F.resub(t, r"this\.tickers = \[[^\]]*\];", "this.tickers = LIVE.tickers;", 1, w)
    t = F.resub(t, r"var desk = \[\n.*?\n    \];\n    desk\.forEach\(function \(g, i\) \{[^\n]*\n", "var desk = LIVE.gates;\n", 1, w)
    t = F.resub(t, r"deskAria: '[^']*' \+ d\.date \+ '\.',", "deskAria: LIVE.chart.aria + ' Showing ' + d.date + '.',", 1, w)
    t = F.sub(t, "(top.s.k === 'cash' ? ' lead' : ' leads')", "(/ in cash$| alike$/.test(top.s.label) ? ' lead' : ' leads')", 1, w)
    # markup
    t = F.sub(t, '<span class="asof">As of 12 Oct 2026</span>', '<span class="asof">As of {{ L.asof }}</span>', 3, w)
    t = F.resub(t, r'<div class="verdict">\s*<h3>The ghost is ahead\.</h3>\s*<p>[^<]*</p>\s*</div>',
                '<div class="verdict">\n<h3>{{ L.verdict.h }}</h3>\n<p>{{ L.verdict.p }}</p>\n</div>', 1, w)
    t = F.sub(t, '<span class="chart-t">Return since 9 Sep 2026</span>', '<span class="chart-t">Return since 9 Sep 2026, to {{ L.asof }}</span>', 1, w)
    t = F.sub(t, '<span>Three in cash: Cash only so far, earning the Treasury bill rate.</span>',
              '<sc-if value="{{ L.cashLegend }}"><span>{{ L.cashLegend }}</span></sc-if>', 1, w)
    t = chart_markup(F, t, w)
    t = F.sub(t, 'type="range" min="0" max="23"', 'type="range" min="0" max="{{ L.chart.n }}"', 1, w)
    t = F.resub(t, r'<tbody>\s*<tr><td class="who">Tobias Lindgren.*?</tbody>',
                '<tbody>\n<tr data-for="{{ L.table }}" data-as="b" class="{{ b.cls }}"><td class="who">{{ b.who }}<small>{{ b.sub }}</small></td>'
                '<td data-l="Return" class="r">{{ b.ret }}</td><td data-l="Worst drop" class="r">{{ b.mdd }}</td>'
                '<td data-l="Invested" class="r">{{ b.inv }}</td><td data-l="Against the ghost" class="r {{ b.vsCls }}">'
                '<span data-if="{{ b.tri }}" class="tri {{ b.tri }}" aria-hidden="true"></span>{{ b.vs }}</td></tr>\n</tbody>', 1, w)
    t = F.sub(t, '<span>30 changes made by agents have merged. Human approvals: 0.</span>',
              '<span>{{ L.prs }} changes made by agents have merged. Human approvals: 0.</span>', 1, w)
    t = F.sub(t, '3 orders were refused by code, each published with the reason.',
              '{{ L.refusedN }} orders were refused by code, each published with the reason.', 1, w)
    t = F.sub(t, '<caption><span class="asof">As of {{ L.asof }}</span></caption>',
              '<caption><span class="asof">As of {{ L.asof }}. Invested: the average share of the book in instruments since 9 Sep.</span></caption>', 1, w)

    series = series_groups(F, R, RC)
    cash = [s for s in series if s['k'] == 'cash']
    live = dict(C)
    tick = sorted(p['instrument'] for p in R['va']['books'][R['ghost']]['positions'])
    live.update({'dates': R['dates'], 'nav': R['nav'], 'series': series, 'chart': chart_live(F, R, RC, CH),
                 'verdict': verdict_live(F, R, RC), 'table': table_rows(F, R, RC), 'gates': gates_live(F, R, RC),
                 'tickers': tick, 'prs': len(R['agent_prs']), 'refusedN': len(R['refusals']),
                 'cashLegend': ('%s: Cash only so far, earning the Treasury bill rate.' % cash[0]['label']) if cash else ''})
    if len(tick) != 27:
        raise SystemExit('proof: the ghost should hold the 27 instruments it bought on day one, it holds %d' % len(tick))
    return t, live


# ---------------------------------------------------------------- Books (new page)
HISTORY_DAYS = 20
BOOKS_CSS = r'''
<style>
.bk-intro{padding-top:88px;padding-bottom:56px}
.bk-intro .lede{margin-top:24px;max-width:46em}
.bk-intro .asof{margin-top:20px}
.bk-index{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:40px}
.bk-pick{display:grid;grid-template-columns:44px 1fr auto;gap:4px 14px;align-items:center;padding:14px 16px;border:.75px solid var(--rule7);border-radius:3px;background:var(--prussian);color:var(--plotter);text-align:left;font:inherit;cursor:pointer;transition:border-color .15s,box-shadow .15s}
.bk-pick:hover{border-color:var(--plotter)}
.bk-pick.is-sel{border-color:var(--highlight);box-shadow:inset 0 0 0 1.5px var(--highlight)}
.bk-pick.is-ghost{border-style:dashed;background:transparent}
.bk-pick img,.bk-pick .gface{grid-row:1 / span 2;width:44px;height:44px;border-radius:50%;background:var(--note)}
.bk-pick .gface{border:1.5px dashed var(--ghost)}
.bk-pick b{font-weight:600;font-size:16px;line-height:20px}
.bk-pick small{grid-column:2;color:var(--muted);font-size:13.6px;line-height:18px}
.bk-pick .r{grid-row:1;grid-column:3;justify-self:end;font-variant-numeric:tabular-nums;font-weight:600}
.bk-pick .v{grid-row:2;grid-column:3;justify-self:end;font-size:13.6px;font-variant-numeric:tabular-nums}
.ahead{color:var(--intaglio)}
.behind{color:var(--pencil-text)}
.bk-panel{margin-top:48px;padding:40px;border:.75px solid var(--rule7);background:var(--whiteprint)}
.bk-head{display:grid;grid-template-columns:72px 1fr auto;gap:8px 20px;align-items:start}
.bk-head img,.bk-head .gface{width:72px;height:72px;border-radius:50%}
.bk-head .gface{display:block;border:1.5px dashed var(--ghost)}
.bk-name{margin:0}
.bk-role{color:var(--muted);margin-top:4px}
.bk-mandate{margin-top:14px;font-size:18px;line-height:27px;max-width:40em}
.bk-links{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px;font-size:15px}
.bk-figs{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:0;margin-top:32px;border-top:.75px solid var(--rule7);border-bottom:.75px solid var(--rule7)}
.bk-figs div{padding:14px 16px 16px 0}
.bk-figs dt{font-size:13.6px;color:var(--muted)}
.bk-figs dd{margin:4px 0 0;font-size:22px;line-height:28px;font-weight:600;font-variant-numeric:tabular-nums}
.bk-figs dd small{display:block;font-size:13px;font-weight:400;color:var(--muted)}
.bk-row{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:40px;margin-top:36px;align-items:start}
.bk-row>div,.bk-panel,.bk-day>div{min-width:0}
.bk-h3{font-size:19px;font-weight:620;margin:0 0 14px}
.bk-bar{display:flex;height:22px;border:.75px solid var(--rule7);overflow:hidden}
.bk-bar span{display:block;height:100%;border-right:1px solid var(--whiteprint)}
.bk-bar .cash{background:repeating-linear-gradient(135deg,transparent 0 3px,var(--rule3) 3px 4px)}
.bk-bar .pos{background:var(--intaglio)}
.bk-bar .pos:nth-child(odd){background:var(--tint)}
.bk-barl{display:flex;justify-content:space-between;margin-top:6px;font-size:13.6px;color:var(--muted)}
.bk-spark svg{display:block;width:100%;height:auto}
.bk-spark .s-b{fill:none;stroke:var(--plotter);stroke-width:1.6}
.bk-spark .s-g{fill:none;stroke:var(--ghost);stroke-width:1.4;stroke-dasharray:5 4}
.bk-spark .s-0{stroke:var(--rule);stroke-width:1}
.bk-spark p{font-size:13.6px;color:var(--muted);margin-top:6px}
.bk-tbl{width:100%;border-collapse:collapse;font-size:15.5px}
.bk-tbl th{text-align:left;font-weight:500;font-size:13.6px;color:var(--muted);padding:8px 12px 8px 0;border-bottom:.75px solid var(--rule7)}
.bk-tbl td{padding:10px 12px 10px 0;border-bottom:.75px solid var(--rule);vertical-align:top}
.bk-tbl .r{text-align:right;font-variant-numeric:tabular-nums}
.bk-tbl small{display:block;color:var(--muted);font-size:13px}
.bk-tblw{overflow-x:auto;margin-top:8px}
.bk-rec{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.bk-rec span{width:14px;height:14px;border:.75px solid var(--rule7)}
.bk-rec .moved{background:var(--intaglio);border-color:var(--intaglio)}
.bk-rec .refused{background:var(--pencil);border-color:var(--pencil)}
.bk-rec .held{background:transparent}
.bk-key{display:flex;gap:18px;flex-wrap:wrap;margin-top:8px;font-size:13.6px;color:var(--muted)}
.bk-key i{display:inline-block;width:11px;height:11px;margin-right:6px;vertical-align:-1px;border:.75px solid var(--rule7)}
.bk-key .moved{background:var(--intaglio)}.bk-key .refused{background:var(--pencil)}
.bk-days{list-style:none;margin:8px 0 0;padding:0}
.bk-day{display:grid;grid-template-columns:120px 1fr;gap:20px;padding:20px 0;border-top:.75px solid var(--rule)}
.bk-day time{font-variant-numeric:tabular-nums;font-weight:600}
.bk-day time small{display:block;font-weight:400;color:var(--muted);font-size:13px}
.bk-note{font-family:var(--doc);font-style:italic;font-size:17px;line-height:26px}
.bk-note-l{font-size:13px;color:var(--muted);margin-top:4px}
.bk-ord{margin-top:12px;padding-left:14px;border-left:2px solid var(--intaglio)}
.bk-ord.ref{border-left-color:var(--pencil)}
.bk-ord b{font-weight:600}
.bk-ord .why{font-family:var(--doc);font-style:italic}
.bk-ord .meta{font-size:13.6px;color:var(--muted)}
.bk-more{margin-top:20px}
.bk-ghostnote{margin-top:12px;color:var(--muted);max-width:46em}
@media (max-width:1100px){.bk-index{grid-template-columns:repeat(2,minmax(0,1fr))}.bk-figs{grid-template-columns:repeat(3,minmax(0,1fr))}.bk-row{grid-template-columns:1fr}}
@media (max-width:640px){.bk-tbl .opt{display:none}.bk-tbl td small{max-width:14em}.bk-index{grid-template-columns:1fr}.bk-panel{padding:20px 16px}.bk-head{grid-template-columns:56px 1fr}.bk-head img,.bk-head .gface{width:56px;height:56px}.bk-head .bk-asof{grid-column:1 / -1}.bk-figs{grid-template-columns:repeat(2,minmax(0,1fr))}.bk-day{grid-template-columns:1fr;gap:6px}}
</style>
'''

BOOKS_MAIN = '''<main id="main">
<section class="bk-intro" aria-labelledby="bk-h">
<div class="wrap">
<h1 class="h1" id="bk-h" style="grid-column: auto">The books.</h1>
<p class="lede">Nine books on one desk: eight advisors and the ghost. Each started with the same imaginary $100,000 on 9 September. Pick one to see what it holds, what it did each day, and the reason it gave.</p>
<span class="asof">As of {{ L.asof }}. Trading day {{ L.day }}.</span>
<div class="bk-index" role="group" aria-label="Choose a book">
<sc-for list="{{ list }}" as="b"><button type="button" class="bk-pick {{ b.cls }}" aria-pressed="{{ b.pressed }}" onClick="{{ b.on }}"><sc-if value="{{ b.img }}"><img src="{{ b.img }}" width="44" height="44" alt=""></sc-if><sc-if value="{{ b.ghost }}"><span class="gface" aria-hidden="true"></span></sc-if><b>{{ b.name }}</b><span class="r">{{ b.ret }}</span><small>{{ b.role }}</small><span class="v {{ b.vsCls }}">{{ b.vs }}</span></button></sc-for>
</div>
</div>
</section>

<section class="bk-sec" style="padding-bottom: 120px" aria-labelledby="bk-n">
<div class="wrap">
<article class="bk-panel" aria-live="polite">
<div class="bk-head">
<sc-if value="{{ cur.img }}"><img src="{{ cur.img }}" width="72" height="72" alt=""></sc-if><sc-if value="{{ cur.ghost }}"><span class="gface" aria-hidden="true"></span></sc-if>
<div>
<h2 class="bk-name h2" id="bk-n">{{ cur.name }}</h2>
<p class="bk-role">{{ cur.role }}</p>
<p class="bk-mandate quote">“{{ cur.mandate }}”</p>
<p class="bk-links"><sc-if value="{{ cur.brief }}"><a href="{{ cur.brief }}">Read the brief</a></sc-if><a href="{{ cur.ledger }}">The book in the ledger</a></p>
</div>
<span class="asof bk-asof">As of {{ L.asof }}</span>
</div>

<dl class="bk-figs">
<div><dt>Net asset value</dt><dd>{{ cur.nav }}</dd></div>
<div><dt>Return</dt><dd>{{ cur.ret }}<small>since 9 Sep</small></dd></div>
<div><dt>Against the ghost</dt><dd class="{{ cur.vsCls }}">{{ cur.vs }}</dd></div>
<div><dt>Cash</dt><dd>{{ cur.cash }}<small>{{ cur.cashPct }} of the book</small></dd></div>
<div><dt>Invested</dt><dd>{{ cur.invPct }}<small>{{ cur.invAvg }} on average</small></dd></div>
<div><dt>Worst drop</dt><dd>{{ cur.mdd }}<small>from a high</small></dd></div>
</dl>

<div class="bk-row">
<div>
<h3 class="bk-h3">What the book holds</h3>
<div class="bk-bar" role="img" aria-label="{{ cur.barAria }}"><sc-for list="{{ cur.bar }}" as="p"><span class="{{ p.cls }}" style="width: {{ p.w }}%" title="{{ p.t }}"></span></sc-for></div>
<p class="bk-barl"><span>{{ cur.barL }}</span><span>{{ cur.barR }}</span></p>
<sc-if value="{{ cur.hasPos }}">
<div class="bk-tblw">
<table class="bk-tbl">
<caption class="sr">Holdings of {{ cur.name }}, {{ L.asof }}</caption>
<thead><tr><th scope="col">Instrument</th><th scope="col" class="r opt">Quantity</th><th scope="col" class="r opt">Cost</th><th scope="col" class="r">Value</th><th scope="col" class="r">Weight</th><th scope="col" class="r">Return</th></tr></thead>
<tbody><tr data-for="{{ cur.positions }}" data-as="p"><td>{{ p.tk }}<small>{{ p.name }}</small></td><td class="r opt">{{ p.qty }}</td><td class="r opt">{{ p.cost }}</td><td class="r">{{ p.value }}</td><td class="r">{{ p.weight }}</td><td class="r {{ p.cls }}">{{ p.ret }}</td></tr></tbody>
</table>
</div>
</sc-if>
<sc-if value="{{ cur.noPos }}"><p class="bk-ghostnote">Nothing but cash. Idle cash earns the 13-week Treasury bill rate overnight.</p></sc-if>
</div>
<div class="bk-spark">
<h3 class="bk-h3">Return since 9 Sep</h3>
<svg viewBox="0 0 320 120" role="img" aria-label="{{ cur.sparkAria }}"><line class="s-0" x1="0" x2="320" y1="{{ cur.spark.z }}" y2="{{ cur.spark.z }}"></line><path class="s-g" d="{{ cur.spark.g }}"></path><path class="s-b" d="{{ cur.spark.b }}"></path></svg>
<p>{{ cur.sparkNote }}</p>
<sc-if value="{{ cur.hasRec }}">
<h3 class="bk-h3" style="margin-top: 28px">Every trading day</h3>
<div class="bk-rec" role="img" aria-label="{{ cur.recAria }}"><sc-for list="{{ cur.rec }}" as="d"><span class="{{ d.k }}" title="{{ d.t }}"></span></sc-for></div>
<p class="bk-key"><span><i class="moved"></i>Traded</span><span><i></i>Held</span><span><i class="refused"></i>Refused</span></p>
</sc-if>
</div>
</div>

<sc-if value="{{ cur.hasDays }}">
<h3 class="bk-h3" style="margin-top: 44px">Day by day, newest first</h3>
<ol class="bk-days">
<sc-for list="{{ days }}" as="d"><li class="bk-day"><time datetime="{{ d.iso }}">{{ d.date }}<small>{{ d.what }}</small></time><div>
<sc-if value="{{ d.note }}"><p class="bk-note">{{ d.note }}</p><p class="bk-note-l">Note with the orders. Agent writing.</p></sc-if>
<sc-for list="{{ d.orders }}" as="o"><div class="bk-ord"><p><b>{{ o.text }}</b> <span class="meta">{{ o.meta }}</span></p><p class="why">“{{ o.reason }}”</p><sc-if value="{{ o.considered }}"><p class="meta">Also considered: {{ o.considered }}</p></sc-if></div></sc-for>
<sc-for list="{{ d.refused }}" as="o"><div class="bk-ord ref"><p><b>{{ o.text }}</b> <span class="meta">Refused by the risk code</span></p><p class="why">“{{ o.why }}”</p></div></sc-for>
</div></li></sc-for>
</ol>
<div class="bk-more"><sc-if value="{{ moreBtn }}"><button type="button" class="btn" onClick="{{ more }}">{{ moreBtn }}</button></sc-if> <a href="https://github.com/atakanerdim/agent-capital/tree/main/company/data/orders">Every orders file</a></div>
</sc-if>
<sc-if value="{{ cur.ghost }}"><p class="bk-ghostnote">The ghost bought every instrument on the list on 9 September, in equal amounts, and has not traded since. It writes no notes and gives no reasons.</p></sc-if>
</article>
</div>
</section>
</main>'''

BOOKS_SCRIPT = '''<script type="text/x-dc" data-dc-script data-props='{"motion":{"editor":"enum","options":["full","still"],"default":"full","section":"Motion"}}'>
var LIVE = window.LIVE;
var BOOKS = LIVE.books;
class Component extends DCLogic {
  constructor(props) {
    super(props);
    var h = (location.hash || '').slice(1);
    var ok = BOOKS.some(function (b) { return b.k === h; });
    this.state = { sel: ok ? h : BOOKS[0].k, all: false, scrolled: false, hh: 65 };
    this.r = {};
    var self = this;
    this.r.hdr = function (el) { self.hdrEl = el; };
    this.pick = {};
    BOOKS.forEach(function (b) {
      self.pick[b.k] = function () {
        self.setState({ sel: b.k, all: false });
        try { history.replaceState(null, '', '#' + b.k); } catch (e) {}
      };
    });
    this.more = function () { self.setState({ all: !self.state.all }); };
    this.onScroll = function () { var y = window.scrollY > 8; if (y !== self.state.scrolled) self.setState({ scrolled: y }); };
    this.onHash = function () { var k = (location.hash || '').slice(1); if (self.pick[k] && k !== self.state.sel) self.setState({ sel: k, all: false }); };
  }
  componentDidMount() {
    window.addEventListener('scroll', this.onScroll, { passive: true });
    window.addEventListener('hashchange', this.onHash);
    if (this.hdrEl) { var hh = Math.round(this.hdrEl.offsetHeight); if (hh) this.setState({ hh: hh }); }
  }
  componentWillUnmount() { window.removeEventListener('scroll', this.onScroll); window.removeEventListener('hashchange', this.onHash); }
  renderVals() {
    var s = this.state, self = this;
    var cur = BOOKS.filter(function (b) { return b.k === s.sel; })[0];
    var list = BOOKS.map(function (b) {
      return { name: b.name, role: b.role, ret: b.ret, vs: b.vsShort, vsCls: b.vsCls, img: b.img, ghost: b.ghost,
               cls: (b.ghost ? 'is-ghost' : '') + (b.k === s.sel ? ' is-sel' : ''), pressed: b.k === s.sel ? 'true' : 'false', on: self.pick[b.k] };
    });
    var days = s.all ? cur.days : cur.days.slice(0, 5);
    var moreBtn = cur.days.length > 5 ? (s.all ? 'Show the last five days' : 'Show all ' + cur.days.length + ' days') : '';
    return { siteCls: 'm-anim', hdrCls: s.scrolled ? 'is-scrolled' : '', hh: s.hh, r: this.r,
             list: list, cur: cur, days: days, more: this.more, moreBtn: moreBtn };
  }
}
</script>'''


def spark(F, R, k):
    """A small return line for one book against the ghost, 320 x 120."""
    def rets(key):
        return [(v / 100000 - 1) * 100 for v in R['nav'][key]]
    b, g = rets(k), rets(R['ghost'])
    lo, hi = min(b + g + [0.0]), max(b + g + [0.0])
    pad = max(0.25, (hi - lo) * 0.08)
    lo, hi = lo - pad, hi + pad
    n = len(b) - 1
    x = lambda i: round(4 + i * 312 / max(n, 1), 1)
    y = lambda v: round(8 + (hi - v) / (hi - lo) * 104, 1)
    path = lambda s: 'M' + ' L'.join('%s %s' % (x(i), y(v)) for i, v in enumerate(s))
    return {'b': path(b), 'g': path(g), 'z': y(0.0)}


def instrument_names(R):
    names = {k: v.get('name', k) for k, v in R['vs']['instruments'].items()}
    for k, q in R['prices']['quotes'].items():
        names.setdefault(k, q.get('name', k))
    return names


def books(F, R, RC, CH, C):
    w = 'books'
    base = F.tpl('proof.dc.html')
    head = base[:base.index('<x-dc>')]
    head = F.resub(head, r'<title>.*?</title>', '<title>The books — Crestpoint Analytics</title>', 1, w)
    head = F.sub(head, '</helmet>', BOOKS_CSS + '</helmet>', 1, w)
    body = re.search(r'<x-dc>(.*?)</x-dc>', base, re.S).group(1)
    top, rest = body.split('<main id="main">', 1)
    foot = rest.split('</main>', 1)[1]
    foot = F.sub(foot, '<span class="tb-l">Page</span><span class="tb-v">Proof</span>',
                 '<span class="tb-l">Page</span><span class="tb-v">Books</span>', 1, w)
    t = head + '<x-dc>' + top + BOOKS_MAIN + foot + '</x-dc>\n' + BOOKS_SCRIPT + '\n'

    names = instrument_names(R)
    g = R['rows'][R['ghost']]
    order = [b['k'] for b in sorted(RC['books'], key=lambda b: -b['ret'])] + [R['ghost']]
    dates = R['dates']
    hist_days = sorted(R['orders'])[-HISTORY_DAYS:]
    out = []
    for k in order:
        bk = R['va']['books'][k]
        row = R['rows'][k]
        ghost = k == R['ghost']
        avg, last = R['inv'][k]
        nav = bk['nav']
        vsv = row['return_pct'] - g['return_pct']
        if ghost:
            vs, vss, vsc = '—', 'the ghost', ''
        elif abs(vsv) < 0.005:
            vs, vss, vsc = 'level', 'level with the ghost', ''
        else:
            vs = '%.2f pp %s' % (abs(vsv), 'ahead' if vsv > 0 else 'behind')
            vss, vsc = vs, ('ahead' if vsv > 0 else 'behind')
        positions = []
        for p in sorted(bk['positions'], key=lambda p: -p['value']):
            r = p.get('return_pct', 0.0)
            positions.append({'tk': p['instrument'], 'name': names.get(p['instrument'], ''),
                              'qty': ('%.4f' % p['qty']).rstrip('0').rstrip('.'), 'cost': F.usd(p['cost'], True),
                              'value': F.usd(p['value'], True) + ('' if p.get('priced', True) else ' (at cost)'),
                              'weight': '%.1f%%' % (p['value'] / nav * 100), 'ret': F.pct(r),
                              'cls': 'ahead' if r > 0.005 else ('behind' if r < -0.005 else '')})
        bar = [{'cls': 'cash', 'w': round(bk['cash'] / nav * 100, 2), 't': 'Cash, %s' % F.usd(bk['cash'], True)}]
        bar += [{'cls': 'pos', 'w': round(p['value'] / nav * 100, 2), 't': '%s, %s' % (p['instrument'], F.usd(p['value'], True))}
                for p in sorted(bk['positions'], key=lambda p: -p['value'])]
        rec_words = {'held': 'held', 'moved': 'traded', 'refused': 'refused'}
        rec = [{'k': x if x in rec_words else 'held', 't': '%s: %s' % (F.D(dates[i]), rec_words.get(x, x))}
               for i, x in enumerate(bk.get('record') or [])]
        counts = {x: sum(1 for r in bk.get('record') or [] if r == x) for x in ('moved', 'held', 'refused')}
        days = []
        if not ghost:
            for d in reversed(hist_days):
                x = R['orders'][d].get(k)
                if not x:
                    continue
                os_ = []
                for o in x.get('orders') or []:
                    meta = 'At %s.' % F.usd(o['price'], True) if o.get('price') else ''
                    if o.get('conviction') is not None:
                        meta += ' Conviction %s.' % ('%.2f' % o['conviction']).rstrip('0').rstrip('.')
                    if o.get('horizon_days'):
                        meta += ' Horizon %d days.' % o['horizon_days']
                    cons = '; '.join('%s (%s)' % (c['instrument'], c.get('why_not', '').strip().rstrip('.'))
                                     for c in (o.get('considered') or []) if c.get('instrument'))
                    os_.append({'text': order_text(o['action'], o['instrument'], o.get('amount_usd', 0)) + '.',
                                'meta': meta.strip(), 'reason': clean((o.get('reason') or '').strip(), True), 'considered': clean(cons)})
                rf = [{'text': order_text(r['order']['action'], r['order']['instrument'], r['order'].get('amount_usd', 0)) + '.',
                       'why': r['why']} for r in (x.get('rejected') or [])]
                what = 'traded' if os_ else ('refused' if rf else 'held')
                if os_ and rf:
                    what = 'traded, one refused' if len(rf) == 1 else 'traded, %d refused' % len(rf)
                utc = (x.get('decided_utc') or '')[11:16]
                days.append({'iso': d, 'date': F.D(d), 'what': what + (', %s UTC' % utc if utc else ''),
                             'note': clean((x.get('note') or '').strip(), True), 'orders': os_, 'refused': rf})
        sp = spark(F, R, k)
        first = row['name'].split()[0]
        out.append({
            'k': k, 'name': 'Buy and hold' if ghost else row['name'], 'ghost': ghost,
            'role': 'the desk’s ghost, never traded' if ghost else 'advisor, %s' % ROLE[k],
            'img': '' if ghost else 'assets/portraits/crestpoint/%s.svg' % k, 'mandate': row['mandate'],
            'brief': '' if ghost else 'https://github.com/atakanerdim/agent-capital/blob/main/company/agents/prompts/%s.md' % k,
            'ledger': 'https://github.com/atakanerdim/agent-capital/blob/main/company/data/portfolios/%s.json' % k,
            'nav': F.usd(nav, True), 'ret': F.pct(row['return_pct']), 'vs': vs, 'vsShort': vss, 'vsCls': vsc,
            'cash': F.usd(bk['cash'], True), 'cashPct': '%.1f%%' % (bk['cash'] / nav * 100),
            'invPct': '%.1f%%' % last, 'invAvg': '%.1f%%' % avg, 'mdd': '%.2f%%' % row['max_drawdown_pct'],
            'positions': positions, 'hasPos': bool(positions), 'noPos': not positions,
            'bar': bar, 'barL': 'Cash %.1f%%' % (bk['cash'] / nav * 100),
            'barR': '%d holding%s' % (len(positions), '' if len(positions) == 1 else 's'),
            'barAria': 'Cash %.1f%%%s' % (bk['cash'] / nav * 100, ''.join(', %s %.1f%%' % (p['tk'], p['value_raw'] if False else float(p['weight'][:-1])) for p in positions)),
            'spark': sp, 'sparkAria': 'Return of %s since 9 Sep against the ghost: %s and %s.' % (first if not ghost else 'the ghost', F.pct(row['return_pct']), F.pct(g['return_pct'])),
            'sparkNote': 'Solid line: %s. Dashed: the ghost, %s.' % ('the ghost' if ghost else first, F.pct(g['return_pct'])),
            'rec': rec, 'hasRec': bool(rec),
            'recAria': '%d trading days: traded on %d, held on %d, refused on %d.' % (len(rec), counts['moved'], counts['held'], counts['refused']),
            'days': days, 'hasDays': bool(days),
        })
    live = dict(C)
    live.update({'books': out})
    return t, live


# ---------------------------------------------------------------- How it runs
def how_it_runs(F, R, RC, CH, C):
    w = 'how'
    t = F.tpl('how-it-runs.dc.html')
    asof = R['asof']
    day = R['orders'][asof]
    N = len(R['dates'])
    kinds, times = {}, []
    for a in DESK:
        x = day.get(a, {})
        if x.get('orders'):
            kinds[a] = 'moved'
        elif x.get('rejected'):
            kinds[a] = 'refused'
        else:
            kinds[a] = 'held'
        if x.get('decided_utc'):
            times.append(x['decided_utc'][11:16])
    n_m = sum(1 for v in kinds.values() if v == 'moved')
    n_h = sum(1 for v in kinds.values() if v == 'held')
    n_ref = sum(len(day.get(a, {}).get('rejected') or []) for a in DESK)
    decided = '%s traded, %s held.' % (F.word(n_m, True), F.word(n_h))
    if n_ref:
        decided += ' %s order%s refused.' % (F.word(n_ref, True), ' was' if n_ref == 1 else 's were')
    by = {}
    for k, q in sorted(R['prices']['quotes'].items()):
        by.setdefault(q['source'], []).append(k)
    universe = R['vs']['feed']['universe']
    covered = R['vs']['feed']['covered']
    sweep = R['vs']['sweep']['pct']
    dd = dt.date.fromisoformat(asof)
    long_day = '%s %d %s' % (['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][dd.weekday()], dd.day,
                             ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][dd.month - 1])
    filled = [(a, o) for a in DESK for o in (day.get(a, {}).get('orders') or [])]
    refused = [(a, r['order']) for a in DESK for r in (day.get(a, {}).get('rejected') or [])]
    cash = [b for b in RC['books'] if b['never']]

    # --- logic
    t = script_dates_nav(F, t, w)
    t = F.resub(t, r"var ADV = \[.*?\n\];", "var ADV = LIVE.adv;", 1, w)
    t = F.resub(t, r"var YAHOO = \[[^\]]*\];", "var PROV = LIVE.providers;", 1, w)
    t = F.resub(t, r"var FRANK = \[[^\]]*\];\n", "", 1, w)
    t = F.sub(t, "    this.tagsY = YAHOO.map(function (s) { return { s: s, i: i++ }; });\n    this.tagsF = FRANK.map(function (s) { return { s: s, i: i++ }; });",
              "    this.provs = PROV.map(function (p) { return { l: p.l, tags: p.list.map(function (s) { return { s: s, i: i++ }; }) }; });", 1, w)
    t = F.sub(t, "    var c = 'M20 262';\n    for (var j = 1; j < CASH.length; j++) c += ' L' + n1(20 + j * 520 / 23) + ' ' + n1(262 - (CASH[j] - 100000) / 400 * 240);",
              "    var CASH = LIVE.cash.series, CR = LIVE.cash.range, CN = CASH.length - 1;\n    var c = 'M20 262';\n    for (var j = 1; j < CASH.length; j++) c += ' L' + n1(20 + j * 520 / CN) + ' ' + n1(262 - (CASH[j] - 100000) / CR * 240);", 1, w)
    t = F.sub(t, "this.cashLast = 'M' + n1(20 + 22 * 520 / 23) + ' ' + n1(262 - (CASH[22] - 100000) / 400 * 240) + ' L540 ' + n1(262 - (CASH[23] - 100000) / 400 * 240);",
              "this.cashLast = 'M' + n1(20 + (CN - 1) * 520 / CN) + ' ' + n1(262 - (CASH[CN - 1] - 100000) / CR * 240) + ' L540 ' + n1(262 - (CASH[CN] - 100000) / CR * 240);", 1, w)
    t = F.sub(t, "var day = step >= 5 ? 23 : 22;", "var day = step >= 5 ? NL : NL - 1;", 1, w)
    t = F.sub(t, "var sday = step >= 6 ? 23 : 22;", "var sday = step >= 6 ? NL : NL - 1;", 1, w)
    t = F.sub(t, "Math.abs(v) / 2600)", "Math.abs(v) / LIVE.barScale)", 1, w)
    t = F.sub(t, "Math.abs(g) / 2600)", "Math.abs(g) / LIVE.barScale)", 1, w)
    t = F.sub(t, "tagsY: this.tagsY, tagsF: this.tagsF,", "provs: this.provs,", 1, w)
    # --- markup: a day on the desk
    t = F.sub(t, '<p class="lede">Monday 12 October, in six steps.</p>', '<p class="lede">{{ L.longDay }}, in six steps.</p>', 1, w)
    t = F.sub(t, 'Prices arrive for all 35 instruments.', 'Prices arrive for all {{ L.universe }} instruments.', 1, w)
    t = F.sub(t, 'Eight advisors read their own books and decide. One trade, six holds, one refusal.',
              'Eight advisors read their own books and decide. {{ L.decided }}', 1, w)
    t = F.sub(t, 'overnight: 4.05% a year.', 'overnight: {{ L.sweep }} a year.', 1, w)
    t = F.sub(t, '<p class="pane-cap"><b>12 Oct 2026.</b> 35 of 35 instruments priced.</p>',
              '<p class="pane-cap"><b>{{ L.asof }}.</b> {{ L.covered }} of {{ L.universe }} instruments priced.</p>', 1, w)
    t = F.resub(t, r'<div class="prov"><span class="prov-l">yahoo, 30</span>.*?</div></div>\s*<div class="prov"><span class="prov-l">frankfurter, 5</span>.*?</div></div>',
                '<sc-for list="{{ provs }}" as="p"><div class="prov"><span class="prov-l">{{ p.l }}</span><div class="tags"><sc-for list="{{ p.tags }}" as="t"><span class="ptag" style="--i: {{ t.i }}">{{ t.s }}</span></sc-for></div></div></sc-for>', 1, w)
    t = F.sub(t, '<p class="pane-cap"><b>12 Oct 2026,</b> 15:43 to 15:45 UTC</p>', '<p class="pane-cap"><b>{{ L.asof }},</b> {{ L.window }}</p>', 1, w)
    t = F.sub(t, '<p class="pane-cap"><b>12 Oct 2026.</b> The only path from an opinion to the ledger.</p>',
              '<p class="pane-cap"><b>{{ L.asof }}.</b> The only path from an opinion to the ledger.</p>', 1, w)
    t = F.sub(t, '<div class="chip chip-a"><span><b>Emeka Nwosu, macro.</b> Sell XOM, $400.</span><span class="res">Filled</span></div>',
              '<sc-if value="{{ L.chipA }}"><div class="chip chip-a"><span><b>{{ L.chipA.who }}</b> {{ L.chipA.order }}</span><span class="res">Filled</span></div></sc-if>', 1, w)
    t = F.sub(t, '<div class="chip chip-b"><span><b>Ines Kovac, contrarian.</b> Buy TLT, $5,000.</span><span class="res">Refused</span></div>',
              '<sc-if value="{{ L.chipB }}"><div class="chip chip-b"><span><b>{{ L.chipB.who }}</b> {{ L.chipB.order }}</span><span class="res">Refused</span></div></sc-if>', 1, w)
    t = F.resub(t, r'<p class="pane-cap"><b>Cash only so far, earning the Treasury bill rate\.</b> Tobias, Beatriz and Marisol, 9 Sep to 12 Oct 2026\.</p>',
                '<p class="pane-cap"><b>{{ L.cash.head }}</b> {{ L.cash.who }}, 9 Sep to {{ L.asof }}.</p>', 1, w)
    t = F.sub(t, '<span class="t" style="right: 3%; top: 2%; text-align: right"><b>$100,355.17</b> on 12 Oct, up <b>$33.88</b> since 9 Oct<br>4.05% a year on 12 Oct</span>',
              '<span class="t" style="right: 3%; top: 2%; text-align: right"><b>{{ L.cash.last }}</b> on {{ L.cash.lastD }}, up <b>{{ L.cash.up }}</b> since {{ L.cash.prevD }}<br>{{ L.sweep }} a year on {{ L.cash.rateD }}</span>', 1, w)
    # rules and refusals
    t = F.sub(t, '<div class="rules-h"><h2 class="h2" id="c5-h">The rules</h2><span class="asof">As of 12 Oct 2026</span></div>',
              '<div class="rules-h"><h2 class="h2" id="c5-h">The rules</h2><span class="asof">As of {{ L.asof }}</span></div>', 1, w)
    t = F.sub(t, 'Orders refused so far: <b class="num">3</b>.', 'Orders refused so far: <b class="num">{{ L.refusedN }}</b>.', 1, w)
    t = F.sub(t, '<div class="counter"><span class="n num">3</span>', '<div class="counter"><span class="n num">{{ L.refusedN }}</span>', 1, w)
    t = F.resub(t, r'<tbody>\s*<tr><td class="d">12 Oct 2026<span class="latest">Latest</span>.*?</tbody>',
                '<tbody>\n<tr data-for="{{ L.refusals }}" data-as="f"><td class="d">{{ f.date }}<span data-if="{{ f.latest }}" class="latest">Latest</span></td>'
                '<td>{{ f.who }} {{ f.order }}</td><td class="why">“{{ f.why }}”</td></tr>\n</tbody>', 1, w)
    t = F.sub(t, 'Maintenance commits from 3 September to 12 October 2026: 9.',
              'Maintenance commits from 3 September to {{ L.asof }}: {{ L.maint }}.', 1, w)

    adv = []
    for a in DESK:
        r = R['rows'][a]
        adv.append({'k': a, 'name': r['name'], 'short': r['name'].split()[0],
                    'img': 'assets/portraits/crestpoint/%s.svg' % a, 'day': kinds[a]})
    cs = R['nav'][cash[0]['k']] if cash else R['nav'][RC['books'][0]['k']]
    rng = max(400, -(-max(v - 100000 for v in cs) // 100) * 100 + 50)
    names = [b['name'].split()[0] for b in cash]
    who = (', '.join(names[:-1]) + ' and ' + names[-1]) if len(names) > 1 else (names[0] if names else RC['books'][0]['name'].split()[0])
    prev_i = max(0, N - 1 - 5)
    refl = []
    for i, r in enumerate(reversed(R['refusals'])):
        refl.append({'date': F.D(r['date']), 'latest': i == 0, 'who': '%s, %s.' % (R['rows'][r['adv']]['name'], ROLE[r['adv']]),
                     'order': order_text(r['action'], r['instrument'], r['amount']) + '.', 'why': r['why']})
    span = max(abs(v - 100000) for k in list(DESK) + [R['ghost']] for v in R['nav'][k][-2:])
    window = ('%s to %s UTC' % (min(times), max(times))) if times else 'times not recorded'
    if times and min(times) == max(times):
        window = '%s UTC' % times[0]
    live = dict(C)
    live.update({
        'dates': R['dates'], 'nav': R['nav'], 'adv': adv,
        'providers': [{'l': '%s, %d' % (src, len(lst)), 'list': lst} for src, lst in sorted(by.items(), key=lambda x: -len(x[1]))],
        'universe': universe, 'covered': covered, 'sweep': '%.2f%%' % sweep, 'longDay': long_day, 'decided': decided,
        'window': window,
        'chipA': {'who': '%s, %s.' % (R['rows'][filled[0][0]]['name'], ROLE[filled[0][0]]), 'order': order_text(filled[0][1]['action'], filled[0][1]['instrument'], filled[0][1].get('amount_usd', 0)) + '.'} if filled else None,
        'chipB': {'who': '%s, %s.' % (R['rows'][refused[0][0]]['name'], ROLE[refused[0][0]]), 'order': order_text(refused[0][1]['action'], refused[0][1]['instrument'], refused[0][1].get('amount_usd', 0)) + '.'} if refused else None,
        'cash': {'series': cs, 'range': rng, 'who': who,
                 'head': 'Cash only so far, earning the Treasury bill rate.' if cash else 'The leading book.',
                 'last': F.usd(cs[-1], True), 'lastD': F.D(R['dates'][-1], False), 'up': F.usd(cs[-1] - cs[prev_i], True),
                 'prevD': F.D(R['dates'][prev_i], False), 'rateD': F.D(R['vs']['sweep'].get('asof', asof), False)},
        'barScale': max(2600, round(span * 1.08)),
        'refusedN': len(R['refusals']), 'refusals': refl, 'maint': len(R['maint']),
    })
    return t, live
