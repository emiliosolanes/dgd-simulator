"""Build index.html from src/: inlines base.css + dgd.css and app.js into template.html."""
import pathlib
root = pathlib.Path(__file__).resolve().parent.parent
src = root / 'src'
html = (src / 'template.html').read_text(encoding='utf-8')
css = (src / 'base.css').read_text(encoding='utf-8') + '\n' + (src / 'dgd.css').read_text(encoding='utf-8')
js = (src / 'app.js').read_text(encoding='utf-8')
out = html.replace('/*STYLES*/', css).replace('/*APP*/', js)
(root / 'index.html').write_text(out, encoding='utf-8')
print(f'index.html: {len(out):,} bytes')
