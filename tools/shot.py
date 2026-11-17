"""Screenshots via Playwright. Usage: python tools/shot.py '[{"name":"gate","js":"__dgd.setPlaying(false);__dgd.setTime(__dgd.T(3,14,24))"}]'"""
import sys, asyncio, json
from playwright.async_api import async_playwright
import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / 'index.html').as_uri()
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        specs = json.loads(sys.argv[1])
        (ROOT / 'shots').mkdir(exist_ok=True)
        for s in specs:
            pg = await b.new_page(viewport={'width': s.get('w',1600), 'height': s.get('h',900)}, color_scheme=s.get('scheme','light'))
            errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.on('console', lambda m: errs.append('console:'+m.text) if m.type=='error' else None)
            await pg.goto(URL)
            await pg.wait_for_timeout(400)
            js = s.get('js')
            if js: await pg.evaluate(js)
            await pg.wait_for_timeout(s.get('wait', 700))
            await pg.screenshot(path=str(ROOT / 'shots' / (s['name'] + '.png')), full_page=s.get('full', False))
            print(s['name'], 'errors:', [e for e in errs if 'fonts' not in e][:5])
            await pg.close()
        await b.close()
asyncio.run(main())
