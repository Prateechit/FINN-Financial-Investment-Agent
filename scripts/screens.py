"""Capture phone-sized screenshots of the running app using the locally installed Chrome.

python scripts/screens.py [base_url] [out_dir] [route[@scrollY],...] [light|dark] [--full]
"""
import sys

from playwright.sync_api import sync_playwright

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BASE = args[0] if len(args) > 0 else "http://127.0.0.1:5173"
OUT = args[1] if len(args) > 1 else "docs/screens"
ROUTES = args[2].split(",") if len(args) > 2 else ["brief", "alerts", "research", "portfolio", "company/DIXON", "memo/DIXON"]
SCHEME = args[3] if len(args) > 3 else "light"
FULL = "--full" in sys.argv

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                        color_scheme=SCHEME)
    ctx.add_init_script("localStorage.setItem('finn.window', '336')")
    pg = ctx.new_page()
    for spec in ROUTES:
        route, _, y = spec.partition("@")
        pg.goto(f"{BASE}/#/{route}")
        pg.wait_for_timeout(4000)
        if y:
            pg.evaluate(f"window.scrollTo(0, {int(y)})")
            pg.wait_for_timeout(400)
        name = f"{route.replace('/', '_')}{'_' + y if y else ''}{'_dark' if SCHEME == 'dark' else ''}"
        pg.screenshot(path=f"{OUT}/{name}.png", full_page=FULL)
        print("saved", name)
    b.close()
