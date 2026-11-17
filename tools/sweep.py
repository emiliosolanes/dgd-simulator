"""Render every box, view and party view across the timeline, for several what-if settings, and check:
- no render errors
- message consistency (pull on the poll grid, no forward before receipt, GET window covers the returned item)
- party visibility: in a party view, no panel shows a revision newer than that party holds
Usage: python tools/sweep.py   (set CHROME to a Chrome binary if Playwright's Chromium is not installed)
"""
import asyncio, os, pathlib
from playwright.async_api import async_playwright
ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = """(prm) => {
  const H = window.__dgd; H.hideGuide(); H.setPlaying(false); H.setParams(prm);
  const out = []; let n = 0;
  const d = H.data, M = d.MSGS, B = Object.fromEntries(d.BOXES.map(b => [b.id, b]));
  const scopes = ['card', 'doc', 'boxv', 'desks', 'dlist', 'feed', 'alerts', 'x-out', 'plist'];
  for (const box of ['H','P','L','C','G','W']) for (const view of ['chain','doc','box']) for (const lens of ['ALL','SHP','MSC','ECT']) {
    H.select(box); H.setView(view); H.setLens(lens);
    for (let t = 0; t <= H.T(5,12,0); t += 53) {
      H.setTime(t);
      try { H.renderNow(); n++; } catch (e) { out.push(['render', box, view, lens, t, e.message].join(' ')); if (out.length > 8) return out; continue; }
      if (lens === 'ALL') continue;
      const h = d.held(B[box], lens, t), max = h ? h.n : 0, issued = d.issuedAt(B[box], t);
      if (!issued || issued.n <= max) continue;
      const txt = scopes.map(id => { const el = document.getElementById(id); return el && !el.hidden ? el.textContent : ''; }).join(' ') + ' ' + [...document.querySelectorAll('#gantt .g-row')].map(e => e.textContent).join(' ');
      // only this box's own lines matter in the list; other boxes legitimately show their own revisions
      const own = box === 'H' ? txt : ((document.getElementById('card').hidden ? '' : document.getElementById('card').textContent) + (document.getElementById('doc').hidden ? '' : document.getElementById('doc').textContent) + document.getElementById('desks').textContent);
      for (let k = max + 1; k <= issued.n; k++) if (new RegExp('\\\\br' + k + '\\\\b').test(own) && box !== 'H') out.push(['leak', box, view, lens, t, 'r' + k].join(' '));
      if (box === 'H') { const scoped = (document.getElementById('card').hidden ? '' : document.getElementById('card').textContent) + (document.getElementById('doc').hidden ? '' : document.getElementById('doc').textContent) + document.getElementById('desks').textContent + [...document.querySelectorAll('#dlist .vrow.sel')].map(e => e.textContent).join(' ') + [...document.querySelectorAll('#gantt .g-row')].map(e => e.textContent).join(' ') + document.getElementById('x-out').textContent;
        for (let k = max + 1; k <= issued.n; k++) if (new RegExp('\\\\br' + k + '\\\\b').test(scoped)) out.push(['leak', box, view, lens, t, 'r' + k].join(' ')); }
      if (out.length > 8) return out;
    }
  }
  for (const m of M) {
    const P = m.pull ? (m.to === 'ECT' ? prm.ectPoll : prm.shpPoll) : 0;
    if (m.pull && m.t % P !== 0) out.push('pull off-grid ' + m.id);
    if (m.pull && m.k === 'D' && B[m.box].revs[m.rev - 1].t < m.qmin) out.push('GET /dgds window misses ' + m.id);
    if (m.pull && m.fb && m.fb.t < m.qmin) out.push('GET /dgd-feedbacks window misses ' + m.id);
    if (m.k === 'D' && m.from !== 'SHP') { if (!M.find(x => x.box === m.box && x.k === 'D' && x.to === m.from && x.rev === m.rev && x.t <= m.t)) out.push('forward before receipt ' + m.id); }
    if (m.fb && m.fb.origin !== m.from) { if (!M.find(x => x.fb && x.fb.id === m.fb.id && x.to === m.from && x.t <= m.t)) out.push('relay before receipt ' + m.id); }
    if (m.fb && m.t < m.fb.t) out.push('feedback delivered before it was created ' + m.id);
  }
  return out.concat(['renders ' + n, 'messages ' + M.length, 'released ' + d.EV.rel + (d.EV.made ? ' made' : ' missed')]);
}"""
async def main():
    bad = 0
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get('CHROME') or None, args=['--no-sandbox'])
        runs = [((1600, 900), {'ectPoll': 30, 'shpPoll': 30, 'fix': 60}), ((390, 844), {'ectPoll': 30, 'shpPoll': 30, 'fix': 60}),
                ((1280, 760), {'ectPoll': 5, 'shpPoll': 5, 'fix': 30}), ((1600, 900), {'ectPoll': 60, 'shpPoll': 60, 'fix': 180, 'reapprove': 180}), ((1600, 900), {'ectPoll': 15, 'shpPoll': 60, 'fix': 120})]
        import sys
        if len(sys.argv) > 1: runs = [runs[int(i)] for i in sys.argv[1].split(',')]
        for vw, prm in runs:
            pg = await b.new_page(viewport={'width': vw[0], 'height': vw[1]})
            errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
            await pg.goto((ROOT / 'index.html').as_uri()); await pg.wait_for_timeout(300)
            res = await pg.evaluate(JS, prm)
            issues = res[:-3] + errs
            bad += len(issues)
            print(vw, prm, res[-3:], 'issues:', issues[:8])
            await pg.close()
        await b.close()
    print('OK' if not bad else f'{bad} issues')
asyncio.run(main())
