"""Read-only, bounded ledger snapshots and loopback status server."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import parse_qs, urlsplit

from ticket_controls import control


def snapshot(home, after=0, limit=100):
    if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('after must be nonnegative; limit must be between 1 and 500')
    con = sqlite3.connect((home / 'ledger.sqlite3').resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute('BEGIN')  # tickets and events describe the same read snapshot
        tickets = []
        for r in con.execute('SELECT * FROM tickets ORDER BY updated DESC,id'):
            review = json.loads(r['review_json']) if r['review_json'] else {}
            risk = review.get('risk', {})
            tickets.append({'id': r['id'], 'title': json.loads(r['ticket'])['title'], 'state': r['state'],
                            'head': r['head_sha'], 'attempts': r['attempts'], 'updated': r['updated'],
                            'risk': risk.get('level'), 'human_required': risk.get('requires_human', False),
                            'human_reviewer': review.get('human_approval', {}).get('reviewer'),
                            'error': r['error'], 'pr_url': r['pr_url'], **control(con, r['id'])})
        events = []
        for r in con.execute('SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT ?', (after, limit + 1)):
            d = json.loads(r['details'])
            events.append({'sequence': r['sequence'], 'ticket': r['ticket_id'], 'state': r['state'],
                           'at': r['at'], 'action': d.get('action', 'transition'),
                           'head': d.get('head_sha', d.get('head')), 'error': d.get('error'),
                           'reason': d.get('reason')})
        more = len(events) > limit
        events = events[:limit]
        return {'tickets': tickets, 'events': events, 'cursor': events[-1]['sequence'] if events else after,
                'has_more': more, 'coordinator_locked': (home / 'coordinator.lock').exists(),
                'recorded_at': time.time(), 'verification': 'Recorded ledger state; publish revalidates current evidence.'}
    finally:
        con.close()


def events(home, after, limit, follow):
    while True:
        data = snapshot(home, after, limit)
        print(json.dumps(data), flush=True)
        after = data['cursor']
        if not follow:
            return
        if not data['has_more']:
            time.sleep(2)


def server(home, port=8765):
    assets = Path(__file__).with_name('web')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, payload, kind='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', kind + '; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if (self.headers.get('Host') not in allowed or
                    (self.headers.get('Origin') and self.headers['Origin'] not in {'http://' + x for x in allowed}) or
                    self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.send(403, b'{"error":"loopback same-origin access required"}')
                return
            url = urlsplit(self.path)
            static = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if url.path in static:
                filename, kind = static[url.path]
                self.send(200, (assets / filename).read_bytes(), kind)
            elif url.path == '/api/snapshot':
                try:
                    args = parse_qs(url.query)
                    data = snapshot(home, int(args.get('after', ['0'])[0]), int(args.get('limit', ['100'])[0]))
                    self.send(200, json.dumps(data).encode())
                except (ValueError, KeyError, TypeError, sqlite3.Error, OSError):
                    self.send(400, b'{"error":"Invalid cursor/limit or ledger unavailable"}')
            else:
                self.send(404, b'{"error":"Not found"}')
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('Invalid port')
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def serve(home, port):
    httpd = server(home, port)
    print(f'Factory ledger: http://127.0.0.1:{httpd.server_port} (read only)', flush=True)
    try:
        httpd.serve_forever(poll_interval=.5)
    finally:
        httpd.server_close()
