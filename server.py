"""Servidor local: site público e painel administrativo local."""
import argparse
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
from contextlib import closing

from flask import Flask, abort, g, render_template, request, session

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT.parent / '.fotografia-admin'
PUBLIC_FILES = {'styles.css', 'admin.css'}


def create_app(test_config=None):
    app = Flask(__name__, static_folder=None, template_folder=str(ROOT / 'templates'))
    app.config.update(
        DATA_DIR=str(DATA_DIR), SECRET_KEY=None,
        SESSION_COOKIE_NAME='fg_admin', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=False,
        MAX_CONTENT_LENGTH=8192, MAX_FORM_PARTS=20,
        TRUSTED_HOSTS=['localhost', '127.0.0.1'],
    )
    if test_config:
        app.config.update(test_config)
    data = Path(app.config['DATA_DIR'])
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(data, 0o700)
    if not app.config['SECRET_KEY']:
        secret_path = data / 'session.key'
        try:
            fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = secret_path.read_text().strip()
    db_path = data / 'admin.sqlite3'
    with closing(sqlite3.connect(db_path)) as db, db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY CHECK (id = 1), email TEXT NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS challenges (
                id TEXT PRIMARY KEY, code_hash TEXT NOT NULL,
                expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                last_send REAL NOT NULL, sends INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, expires REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
                bucket TEXT NOT NULL, at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS attempts_lookup ON attempts(bucket, at);
        ''')
    os.chmod(db_path, 0o600)
    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(db_path, timeout=25)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        if 'db' in g:
            g.db.close()

    def csrf():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return session['csrf']

    app.jinja_env.globals['csrf_token'] = csrf

    @app.before_request
    def protect_requests():
        if request.method == 'POST':
            supplied = request.form.get('csrf_token', '')
            expected = session.get('csrf', '')
            if not expected or not hmac.compare_digest(supplied, expected):
                abort(400, description='A página expirou. Atualize e tente novamente.')
            origin = request.headers.get('Origin')
            if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
                abort(400, description='Origem da solicitação não permitida.')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; style-src 'self'; script-src 'none'; "
            "img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        if request.path.startswith('/admin'):
            response.headers['Cache-Control'] = 'no-store, private'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.get('/')
    @app.get('/index.html')
    def home():
        return app.response_class((ROOT / 'index.html').read_text(), mimetype='text/html')

    @app.get('/<filename>')
    def asset(filename):
        if filename not in PUBLIC_FILES:
            abort(404)
        return app.response_class((ROOT / filename).read_text(), mimetype='text/css')

    @app.get('/admin')
    @app.get('/admin/')
    def dashboard():
        admin = db().execute('SELECT email FROM admin WHERE id = 1').fetchone()
        return render_template('dashboard.html', email=admin['email'] if admin else None)

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(error):
        descriptions = {400: 'Atualize a página e tente novamente.', 404: 'Esta página não foi encontrada.', 413: 'A solicitação ultrapassou o tamanho permitido.'}
        return render_template('error.html', message=descriptions[error.code]), error.code

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=8081)
    args = parser.parse_args()
    app = create_app()
    app.run(host='127.0.0.1', port=args.port, debug=False)


if __name__ == '__main__':
    main()
