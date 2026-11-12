"""Optional real-browser smoke test; requires Playwright and installed Chromium.

python tests/browser_smoke.py --browser /usr/bin/chromium --artifacts /tmp/factory-browser
The core unittest suite and factory itself have no Playwright dependency.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory
from ledger_view import server


def main():
    from playwright.sync_api import sync_playwright, expect
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', help='installed Chromium executable')
    parser.add_argument('--artifacts', type=Path, help='optional screenshot directory')
    args = parser.parse_args()
    if args.artifacts:
        args.artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary)
        factory.initialize_db(home)
        (home / '.infra-factory').mkdir()
        (home / '.infra-factory/config.json').write_text(json.dumps({'repair_policy': {'max_repairs': 1}}), encoding='utf-8')
        with factory.connect(home) as con:
            con.execute('''INSERT INTO tickets(id,ticket,state,updated,attempts,head_sha,review_json)
                VALUES(?,?,?,?,?,?,?)''', ('DEMO-001', json.dumps({'title': '<img src=x onerror=alert(1)>'}),
                'AWAITING_HUMAN', 1, 1, 'a' * 40, json.dumps({'risk': {'level': 'high', 'requires_human': True}})))
            factory.record(con, 'DEMO-001', 'AWAITING_HUMAN', {'action': 'risk_review'})
        httpd = server(home, 0, repo=home)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=args.browser, headless=True,
                                           args=['--disable-dev-shm-usage'], timeout=20000)
                context = browser.new_context(viewport={'width': 1280, 'height': 900})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{httpd.server_port}', wait_until='domcontentloaded')
                expect(page.locator('#cursor')).to_have_text('Cursor 1', timeout=10000)
                expect(page.locator('#connection')).to_have_text(re.compile('^Live'))
                expect(page.locator('#tickets')).to_contain_text('high · Human required')
                expect(page.locator('#tickets')).to_contain_text('1 / 2')
                expect(page.locator('#tickets img')).to_have_count(0)
                expect(page.locator('#tickets')).to_contain_text('<img src=x onerror=alert(1)>')
                page.locator('#filter').fill('missing')
                expect(page.locator('#tickets')).to_contain_text('No matching tickets')
                page.locator('#filter').fill('')
                if args.artifacts:
                    page.screenshot(path=str(args.artifacts / 'desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                expect(page.locator('h1')).to_be_visible()
                if args.artifacts:
                    page.screenshot(path=str(args.artifacts / 'mobile.png'), full_page=True)
                with factory.connect(home) as con:
                    state, controls = factory.change_control(con, 'DEMO-001', 0, 'Operator inspection')
                    factory.record(con, 'DEMO-001', state, {'action': 'hold', 'reason': 'Operator inspection', **controls})
                expect(page.locator('#cursor')).to_have_text('Cursor 2', timeout=10000)
                expect(page.locator('#tickets')).to_contain_text('HELD: Operator inspection')
                expect(page.locator('#events li')).to_have_count(2)
                context.set_offline(True)
                expect(page.locator('#connection')).to_have_text(re.compile('^Disconnected'), timeout=10000)
                context.set_offline(False)
                expect(page.locator('#connection')).to_have_text(re.compile('^Live'), timeout=10000)
                expect(page.locator('#events li')).to_have_count(2)
                assert not errors, errors
                browser.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()
    print('PASS: live ledger/risk/events, filtering, safe text, desktop/mobile, new hold polling and reconnect without duplicate events')


if __name__ == '__main__':
    main()
