"""Crestpoint Analytics: every number on the front pages, from the desk's own records.

Read by front/assemble.py. Sources, all in this repository:
  site/data/view-standings.json, view-advisor.json   (written by site/build.py, the agents' build)
  company/data/orders/*.json, prices/*.json            (the desk's ledger inputs)
  company/roster.json, company/data/evolution.json      (who works when; the monthly rewrite)
  git log                                               (merges, revision, maintenance)
Nothing is taken from agent prose except quotes, which are shown as quotes and labelled.
"""
import datetime as dt, glob, html, json, os, re, statistics as st, subprocess, sys

NAME = 'Crestpoint Analytics'
URL = 'https://atakanerdim.github.io/agent-capital/'
BASE = '/agent-capital/'
THEME = '#123B2E'
OTHER = '/agent-company/summary.json'
LIVE_LINE = ('<p class="live {{ L.status.cls }}" title="{{ L.status.title }}"><span class="live-dot" aria-hidden="true">'
             '</span><span>{{ L.status.text }}</span><span class="live-date">{{ L.status.date }}</span></p>')
TB_OPTIONAL = set()
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FIRST_DAY = '2026-09-09'
GATE_DAYS, GATE_BREADTH, GATE_INVESTED = 126, 5, 50.0
QUIET_HOURS = 60

MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
         'November', 'December']
WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
WORD = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve']
ADVISORS = ['momentum', 'value', 'macro', 'careful', 'contrarian', 'fx', 'metals', 'index']
PAGES = [('index.html', 'Home', 'Eight AI advisors, the same imaginary $100,000, the same rules. A simulation, not advice.'),
         ('proof.html', 'Proof', 'How Crestpoint’s eight AI advisors compare with a strategy that never thinks, and when we’ll say they’ve beaten it. A simulation, not advice.'),
         ('books.html', 'Books', 'Every book on the desk, the ghost’s included: what it holds, what it did each day and why. Imaginary money.'),
         ('how-it-runs.html', 'How it runs', 'A staff of AI agents, a rulebook they can’t edit, a routine with no sign-off, and a public record. Imaginary money.'),
         ('staff.html', 'Staff', 'Eleven colleagues. None of them people.'),
         ('log.html', 'Log', 'Every change the agents merged into Crestpoint, as it happens.')]
NAV = [('proof.html', 'Proof'), ('books.html', 'Books'), ('how-it-runs.html', 'How it runs'),
       ('staff.html', 'Staff'), ('log.html', 'Log')]
REDIRECTS = {'desk.html': 'books.html', 'office.html': 'staff.html', 'changelog.html': 'log.html', 'index.html': ''}


# ---------------------------------------------------------------- formatting
def D(iso, year=True):
    y, m, d = iso[:10].split('-')
    return '%d %s%s' % (int(d), MON[int(m) - 1], ' ' + y if year else '')


def DL(iso):
    y, m, d = iso[:10].split('-')
    return '%d %s' % (int(d), MONTH[int(m) - 1])


def pct(v, plus=True):
    r = round(v + 0.0, 2)
    if r == 0:
        return '0.00%'
    return ('+' if r > 0 and plus else ('−' if r < 0 else '')) + '%.2f%%' % abs(r)


def pct1(v):
    return '%.1f%%' % v


def usd(v, cents=False):
    return ('$%s' % format(round(v, 2), ',.2f')) if cents else ('$%s' % format(round(v), ',.0f'))


def word(n, cap=False):
    w = WORD[n] if 0 <= n < len(WORD) else str(n)
    return w[0].upper() + w[1:] if cap else w


def load(root, *p):
    return json.load(open(os.path.join(root, *p), encoding='utf-8'))


def git(root, *a):
    return subprocess.run(['git', '-C', root, *a], capture_output=True, text=True, check=True).stdout.strip()


def sub(text, old, new, n=1, where=''):
    c = text.count(old)
    if c != n:
        raise SystemExit('%s: expected %d of %r, found %d' % (where, n, old[:80], c))
    return text.replace(old, new)


def resub(text, pat, new, n=1, where='', flags=re.S):
    out, c = re.subn(pat, new, text, flags=flags)
    if c != n:
        raise SystemExit('%s: expected %d of /%s/, found %d' % (where, n, pat[:80], c))
    return out


# ---------------------------------------------------------------- the records
def records(root):
    vs = load(root, 'site/data/view-standings.json')
    va = load(root, 'site/data/view-advisor.json')
    roster = load(root, 'company/roster.json')
    dates = vs['dates']
    asof = vs['as_of']
    if dates[0] != FIRST_DAY or dates[-1] != asof:
        raise SystemExit('standings dates do not run from %s to %s' % (FIRST_DAY, asof))
    rows = {r['advisor']: r for r in vs['rows']}
    ghost = [r for r in vs['rows'] if r['is_benchmark']][0]['advisor']
    if sorted(a for a in rows if a != ghost) != sorted(ADVISORS):
        raise SystemExit('unexpected advisors: %s' % sorted(rows))
    nav = vs['series']
    for k, s in nav.items():
        if len(s) != len(dates):
            raise SystemExit('series %s has %d points for %d dates' % (k, len(s), len(dates)))
        # the published return must be the series' own last point
        if abs((s[-1] / 100000 - 1) * 100 - rows[k]['return_pct']) > 0.006:
            raise SystemExit('return of %s does not match its series' % k)

    def drawdown(series):
        peak, worst = series[0], 0.0
        for v in series:
            peak = max(peak, v)
            worst = max(worst, (peak - v) / peak * 100)
        return worst

    inv = {}
    for a, al in vs['alloc'].items():
        sh = []
        for day in al['days']:
            parts = sum((day.get('parts') or {}).values())
            cash = day.get('cash', 0)
            if parts + cash > 0:
                sh.append(parts / (parts + cash))
        inv[a] = (100 * st.mean(sh) if sh else 0.0, 100 * sh[-1] if sh else 0.0)

    desk_series = [round(st.mean(nav[a][i] for a in ADVISORS), 2) for i in range(len(dates))]
    desk_ret = (desk_series[-1] / 100000 - 1) * 100
    g_ret = rows[ghost]['return_pct']

    orders = {}
    for f in sorted(glob.glob(os.path.join(root, 'company/data/orders/*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        orders[d['date']] = d['advisors']
    if asof not in orders:
        raise SystemExit('no orders file for %s' % asof)

    refusals = []
    for day in sorted(orders):
        for a, x in orders[day].items():
            for r in x.get('rejected', []) or []:
                o = r['order']
                refusals.append({'date': day, 'adv': a, 'action': o['action'], 'instrument': o['instrument'],
                                 'amount': o.get('amount_usd', 0), 'why': r['why'],
                                 'utc': (x.get('decided_utc') or '')[11:16]})

    prices = load(root, 'company/data/prices/%s.json' % asof)
    by_source = {}
    for q in prices['quotes'].values():
        by_source[q['source']] = by_source.get(q['source'], 0) + 1

    # merges, from the history (CI checks out with fetch-depth 0)
    log = [l.split('\x1f') for l in git(root, 'log', '--format=%H\x1f%cI\x1f%s').splitlines()]
    prs = [l for l in log if re.search(r'\(#\d+\)$', l[2])]
    agent_prs = [l for l in prs if not l[2].startswith('tests:')]
    if not prs:
        raise SystemExit('no merged pull requests in the history (shallow clone?)')
    last_merge = dt.datetime.fromisoformat(prs[0][1]).astimezone(dt.timezone.utc)
    maint = [l for l in log if not re.search(r'\(#\d+\)$', l[2]) and l[1][:10] >= '2026-09-03']

    ev = load(root, 'site/data/evolution.json')
    days_by = {r['id']: r['gunler'] for r in roster}
    return dict(vs=vs, va=va, roster=roster, dates=dates, asof=asof, rows=rows, ghost=ghost, nav=nav, inv=inv,
                drawdown=drawdown, desk_series=desk_series, desk_ret=desk_ret, g_ret=g_ret, orders=orders,
                refusals=refusals, prices=prices, by_source=by_source, agent_prs=agent_prs,
                last_merge=last_merge, maint=maint, ev=ev, days_by=days_by)


# ---------------------------------------------------------------- the race and its gates
def race(R):
    rows, g = R['rows'], R['g_ret']
    N = len(R['dates'])
    books = []
    for a in ADVISORS:
        r = rows[a]
        books.append({'k': a, 'name': r['name'], 'ret': r['return_pct'], 'mdd': r['max_drawdown_pct'],
                      'avg_inv': R['inv'][a][0], 'last_inv': R['inv'][a][1], 'vs': r['return_pct'] - g,
                      'never': R['inv'][a][0] == 0.0 and R['inv'][a][1] == 0.0})
    books.sort(key=lambda b: (-b['ret'], b['name']))
    ahead = [b for b in books if b['vs'] > 0]
    counted = [b for b in ahead if b['avg_inv'] >= GATE_INVESTED]
    never_ahead = [b for b in ahead if b['never']]
    desk_mdd = R['drawdown'](R['desk_series'])
    g_mdd = rows[R['ghost']]['max_drawdown_pct']
    G1 = N >= GATE_DAYS
    G2 = R['desk_ret'] > g
    G3 = len(counted) >= GATE_BREADTH
    claim = G1 and G2 and G3
    gates = [
        {'k': 'g1', 'name': 'Long enough', 'open': G1, 'val': '%d of %d trading days' % (N, GATE_DAYS)},
        {'k': 'g2', 'name': 'The desk is ahead', 'open': G2, 'val': 'Desk %s, ghost %s' % (pct(R['desk_ret']), pct(g))},
        {'k': 'g3', 'name': 'Most advisors are ahead', 'open': G3,
         'val': '%d of 8 ahead while invested, %d needed' % (len(counted), GATE_BREADTH)},
        {'k': 'g4', 'name': 'Ahead while invested', 'open': len(counted) == len(ahead) and len(ahead) > 0,
         'val': 'Only advisors at least half invested on average count'},
    ]

    # The headline, from the state. Never a win before its gate opens.
    if claim:
        h = 'Our advisors are beating a book that never trades.'
    elif G1 and G2:
        h = 'The desk as a whole is ahead of the ghost.'
    elif G2:
        h = 'The desk is ahead of the ghost. Too early to call it.'
    else:
        h = 'The ghost is ahead.'
    parts = []
    if not ahead:
        parts.append('No advisor is ahead of it.')
    elif len(ahead) == len(never_ahead):
        parts.append('Every advisor that traded is behind it.' if len(ahead) < 8 else '')
    else:
        parts.append('%s of eight advisors %s ahead of it.' % (word(len(ahead), True), 'is' if len(ahead) == 1 else 'are'))
    if never_ahead:
        n = len(never_ahead)
        if n == len(ahead):
            parts.append('The %s ahead of it %s placed an order yet; %s gain is the interest on idle cash.'
                         % ('one' if n == 1 else word(n), 'hasn’t' if n == 1 else 'haven’t', 'its' if n == 1 else 'their'))
        else:
            parts.append('%s of them %s placed an order yet; %s gain is the interest on idle cash.'
                         % (word(n, True), 'hasn’t' if n == 1 else 'haven’t', 'its' if n == 1 else 'their'))
    if not claim:
        parts.append('Trading day %d of the %d the claim waits for.' % (N, GATE_DAYS))
    sub_ = ' '.join(p for p in parts if p)
    if G2 and not claim:
        under = ('Ahead is not the same as proven. The claim switches on by itself when the record is long and broad '
                 'enough, and not a day before.')
    elif claim:
        under = 'The gates are open: long enough, broad enough, and ahead while invested.'
    else:
        under = 'We publish it anyway. When the record turns, the claim switches on by itself, and not a day before.'
    return dict(books=books, ahead=ahead, counted=counted, never_ahead=never_ahead, desk_mdd=desk_mdd, g_mdd=g_mdd,
                gates=gates, claim=claim, verdict={'h': h, 'p': sub_, 'under': under})


def chart(R):
    """Scale and ticks for the return charts (the same 1000 x 400 box the design draws in)."""
    vals = [(v / 100000 - 1) * 100 for s in R['nav'].values() for v in s]
    top = max(1, int(-(-max(vals) // 1)))                  # ceil, at least +1%
    bottom = min(-1, int(min(vals) // 1))                  # floor
    if max(vals) > top - 0.15:
        top += 1
    rng = top - bottom + 0.25
    step = 1 if rng <= 7 else 2
    y = lambda v: 20 + (top - v) / rng * 336
    grid, yt = [], []
    v = top
    while v >= bottom - 1e-9:
        cls = 'g0' if abs(v) < 1e-9 else 'gl'
        grid.append({'y': round(y(v), 1), 'cls': cls})
        yt.append({'t': round(y(v) / 400 * 100, 1), 'l': ('+' if v > 0 else ('−' if v < 0 else '')) + '%.1f%%' % abs(v)})
        if v - step / 2 >= bottom - 0.25:
            grid.append({'y': round(y(v - step / 2), 1), 'cls': 'gl2'})
        v -= step
    dates = R['dates']
    n = len(dates) - 1
    idx = sorted({0, round(n / 3), round(2 * n / 3), n})
    xt = []
    for j, i in enumerate(idx):
        cls = 'xt' + ('' if j == 0 else (' xt-e' if i == n else ' xt-c'))
        xt.append({'l': round((70 + i * 730 / max(n, 1)) / 10, 1), 'cls': cls, 't': D(dates[i], False)})
    return {'top': top, 'range': rng, 'grid': grid, 'yt': yt, 'xt': xt, 'n': n}


# ---------------------------------------------------------------- shared page data
def common(R):
    N = len(R['dates'])
    lm = R['last_merge']
    status = {'text': 'Running. Trading day %d.' % N, 'date': D(R['asof']), 'cls': '',
              'title': 'Trading day 1 was 9 Sep 2026. A change merged in the last %d hours, so the light is on.' % QUIET_HOURS,
              'last_merge_utc': lm.isoformat().replace('+00:00', 'Z'), 'quiet_hours': QUIET_HOURS}
    return {'status': status, 'asof': D(R['asof']), 'asofIso': R['asof'], 'day': N,
            'next': {'url': OTHER, 'headline': 'Twelve colleagues, every match', 'asof': ''}}


def folio(R, page, n):
    return {'Folio': '%d of %d' % (n, len(PAGES)), 'Revision': str(len(R['agent_prs'])),
            'Written by': '%d agents' % len(R['roster']), 'As of': D(R['asof'])}


def nav_html(out_name):
    li = ''.join('<li><a href="%s"%s>%s</a></li>' % (h, ' aria-current="page"' if h == out_name else '', t)
                 for h, t in NAV)
    return '<ul class="nav">%s</ul>' % li


def tpl(name):
    return open(os.path.join(HERE, 'pages', name), encoding='utf-8').read()


def build(root):
    R = records(root)
    RC = race(R)
    CH = chart(R)
    C = common(R)
    pages = []
    import pages_cp
    makers = {'index.html': pages_cp.home, 'proof.html': pages_cp.proof, 'books.html': pages_cp.books,
              'how-it-runs.html': pages_cp.how_it_runs}
    import types
    F = types.SimpleNamespace(**globals())
    leave = {r['id']: '2026-10-18' for r in R['roster'] if not r['gunler']}
    staff_log = None
    try:
        import staff_log as staff_log
    except ImportError:
        staff_log = None
    sl = staff_log.build(root, 'CP', {'as_of_iso': R['asof'], 'as_of': D(R['asof']), 'leave': leave}) if staff_log else {}
    for i, (out, label, desc) in enumerate(PAGES, 1):
        if out in makers:
            t, live = makers[out](F, R, RC, CH, C)
        else:
            t = sl.get(out) or tpl(out.replace('.html', '.dc.html'))
            live = dict(C)
        live.update({k: v for k, v in C.items() if k not in live})
        pages.append({'out': out, 'tpl': t, 'desc': desc, 'folio': folio(R, label, i), 'live': live})
    summary = {'headline': '%d trading days' % len(R['dates']), 'asof': 'As of ' + D(R['asof']),
               'ghost': 'Ghost: Buy and hold', 'desk': pct(R['desk_ret']), 'ghost_ret': pct(R['g_ret'])}
    return {'pages': pages, 'nav': nav_html, 'redirects': REDIRECTS, 'summary': summary}

