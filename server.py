"""Servidor local: site público e painel administrativo local."""
import argparse
import calendar
from zoneinfo import ZoneInfo
from datetime import date, datetime, timedelta
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
from contextlib import closing

from flask import Flask, abort, g, redirect, render_template, render_template_string, request, send_file, session

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT.parent / '.fotografia-admin'
PUBLIC_FILES = {'styles.css', 'admin.css'}


def create_app(test_config=None):
    app = Flask(__name__, static_folder=None, template_folder=str(ROOT / 'templates'))
    app.config.update(
        DATA_DIR=str(DATA_DIR), SECRET_KEY=None,
        SESSION_COOKIE_NAME='fg_admin', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=False,
        MAX_CONTENT_LENGTH=12 * 1024 * 1024, MAX_FORM_PARTS=20,
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
    portfolio_dir = data / 'portfolio'
    portfolio_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(portfolio_dir, 0o700)
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
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                visit_date TEXT NOT NULL,
                visit_time TEXT NOT NULL,
                client TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                visit_type TEXT NOT NULL DEFAULT 'reuniao',
                equipment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS visits_date_lookup ON visits(visit_date);
            CREATE TABLE IF NOT EXISTS portfolio_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        ''')
        columns = {row[1] for row in db.execute('PRAGMA table_info(visits)').fetchall()}
        if 'visit_type' not in columns:
            db.execute("ALTER TABLE visits ADD COLUMN visit_type TEXT NOT NULL DEFAULT 'reuniao'")
        if 'equipment' not in columns:
            db.execute("ALTER TABLE visits ADD COLUMN equipment TEXT NOT NULL DEFAULT ''")
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
        images = db().execute(
            'SELECT filename, title, description FROM portfolio_images ORDER BY id DESC LIMIT 5'
        ).fetchall()
        return render_template_string((ROOT / 'index.html').read_text(), portfolio_images=images)

    @app.get('/portfolio')
    def public_portfolio():
        images = db().execute(
            'SELECT filename, title, description FROM portfolio_images ORDER BY id DESC'
        ).fetchall()
        return render_template('public_portfolio.html', images=images)

    @app.get('/<filename>')
    def asset(filename):
        if filename not in PUBLIC_FILES:
            abort(404)
        return app.response_class((ROOT / filename).read_text(), mimetype='text/css')

    @app.get('/admin')
    @app.get('/admin/')
    def dashboard():
        admin = db().execute('SELECT email FROM admin WHERE id = 1').fetchone()
        requested_month = request.args.get('month', '')
        try:
            month_date = datetime.strptime(requested_month, '%Y-%m').date().replace(day=1)
        except ValueError:
            month_date = date.today().replace(day=1)
        message = None
        if request.args.get('saved') == '1':
            message = 'Visita adicionada ao calendário.'
        elif request.args.get('deleted') == '1':
            message = 'Visita excluída do calendário.'
        selected_date = None
        if request.args.get('new_date'):
            try:
                selected_date = date.fromisoformat(request.args['new_date'])
                if not 2 <= selected_date.year <= 9998:
                    raise ValueError
            except ValueError:
                abort(400)
            month_date = selected_date.replace(day=1)
        return render_dashboard(admin, month_date, message=message,
                                open_dialog=selected_date is not None,
                                selected_date=selected_date.isoformat() if selected_date else None)

    def portfolio_page(error=None, status=200):
        images = db().execute(
            'SELECT id, filename, title, description, created_at FROM portfolio_images ORDER BY id DESC'
        ).fetchall()
        message = 'Foto adicionada ao portfólio.' if request.args.get('saved') == '1' else None
        return render_template('portfolio.html', images=images, message=message, error=error), status

    @app.get('/admin/portfolio')
    def portfolio_admin():
        return portfolio_page()

    @app.post('/admin/portfolio/imagens')
    def add_portfolio_image():
        upload = request.files.get('image')
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        if not upload or not upload.filename or not title or len(title) > 120 or len(description) > 500:
            return portfolio_page('Selecione uma foto e preencha o título dentro dos limites indicados.', 400)
        header = upload.stream.read(16)
        upload.stream.seek(0)
        signatures = (
            (header.startswith(b'\xff\xd8\xff'), '.jpg', 'image/jpeg'),
            (header.startswith(b'\x89PNG\r\n\x1a\n'), '.png', 'image/png'),
            (header.startswith(b'RIFF') and header[8:12] == b'WEBP', '.webp', 'image/webp'),
        )
        detected = next(((extension, mime) for valid, extension, mime in signatures if valid), None)
        if not detected:
            return portfolio_page('O arquivo precisa ser uma imagem JPEG, PNG ou WebP válida.', 400)
        extension, mime_type = detected
        filename = f'{secrets.token_hex(16)}{extension}'
        target = portfolio_dir / filename
        upload.save(target)
        os.chmod(target, 0o600)
        try:
            with db() as connection:
                connection.execute(
                    'INSERT INTO portfolio_images (filename, title, description, mime_type, created_at) VALUES (?, ?, ?, ?, ?)',
                    (filename, title, description, mime_type, datetime.now().isoformat(timespec='seconds')),
                )
        except sqlite3.Error:
            target.unlink(missing_ok=True)
            raise
        return redirect('/admin/portfolio?saved=1')

    @app.get('/portfolio/imagens/<filename>')
    @app.get('/admin/portfolio/imagens/<filename>')
    def portfolio_image(filename):
        image = db().execute('SELECT mime_type FROM portfolio_images WHERE filename = ?', (filename,)).fetchone()
        target = portfolio_dir / filename
        if not image or not target.is_file() or target.parent != portfolio_dir:
            abort(404)
        return send_file(target, mimetype=image['mime_type'], conditional=True, max_age=3600)

    def render_dashboard(admin, month_date, message=None, error=None, status=200, open_dialog=False, selected_type='reuniao', equipment_error=False, selected_date=None):
        month_key = month_date.strftime('%Y-%m')
        first_weekday, days_in_month = calendar.monthrange(month_date.year, month_date.month)
        previous_month = (month_date.replace(day=1) - timedelta(days=1)).replace(day=1)
        next_month = (month_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        rows = db().execute(
            'SELECT id, visit_date, visit_time, client, notes, visit_type, equipment FROM visits WHERE visit_date LIKE ? ORDER BY visit_date, visit_time, id',
            (f'{month_key}%',),
        ).fetchall()
        visits_by_date = {}
        for visit in rows:
            visits_by_date.setdefault(visit['visit_date'], []).append(visit)
        weeks = []
        week = [None] * first_weekday
        for day_number in range(1, days_in_month + 1):
            day_key = f'{month_key}-{day_number:02d}'
            week.append({'number': day_number, 'date': day_key, 'visits': visits_by_date.get(day_key, [])})
            if len(week) == 7:
                weeks.append(week)
                week = []
        if week:
            weeks.append(week + [None] * (7 - len(week)))
        month_names = ('janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro')
        return render_template(
            'dashboard.html', email=admin['email'] if admin else None,
            month_label=f'{month_names[month_date.month - 1]} de {month_date.year}',
            month_key=month_key, previous_month=previous_month.strftime('%Y-%m'), next_month=next_month.strftime('%Y-%m'),
            weeks=weeks, today=date.today().isoformat(), message=message, error=error,
            open_dialog=open_dialog, selected_type=selected_type, equipment_error=equipment_error,
            selected_date=selected_date or request.form.get('visit_date') or date.today().isoformat(),
        ), status

    def visit_payload():
        visit_time = request.form.get('visit_time', '').strip()
        visit_hour = request.form.get('visit_hour', '').strip()
        visit_minute = request.form.get('visit_minute', '').strip()
        if visit_hour or visit_minute:
            visit_time = f'{visit_hour}:{visit_minute}'
        payload = {
            'client': request.form.get('client', '').strip(),
            'visit_date': request.form.get('visit_date', '').strip(),
            'visit_time': visit_time,
            'notes': request.form.get('notes', '').strip(),
            'visit_type': request.form.get('visit_type', '').strip().lower(),
            'equipment': request.form.get('equipment', '').strip(),
        }
        try:
            payload['parsed_date'] = date.fromisoformat(payload['visit_date'])
            parsed_time = datetime.strptime(payload['visit_time'], '%H:%M')
            if parsed_time.minute % 5:
                raise ValueError
        except ValueError:
            return None, 'Informe uma data e um horário válidos.'
        if payload['visit_type'] not in {'reuniao', 'ensaio'}:
            return None, 'Escolha se a visita será uma reunião ou um ensaio.'
        if payload['visit_type'] == 'ensaio' and not payload['equipment']:
            return None, 'Informe os equipamentos necessários para o ensaio.'
        if not payload['client'] or len(payload['client']) > 120 or len(payload['notes']) > 500 or len(payload['equipment']) > 500:
            return None, 'Preencha o estabelecimento e mantenha os limites indicados.'
        return payload, None

    @app.post('/admin/visitas')
    def add_visit():
        payload, error = visit_payload()
        if error:
            admin = db().execute('SELECT email FROM admin WHERE id = 1').fetchone()
            month_date = date.today().replace(day=1)
            visit_date = request.form.get('visit_date', '')
            if len(visit_date) >= 7:
                try:
                    month_date = datetime.strptime(visit_date[:7], '%Y-%m').date().replace(day=1)
                except ValueError:
                    pass
            return render_dashboard(admin, month_date, error=error, status=400, open_dialog=True, selected_type=request.form.get('visit_type', 'reuniao'), equipment_error='equipamentos' in error)
        today_local = datetime.now(ZoneInfo('America/Sao_Paulo')).date()
        if (payload['parsed_date'] < today_local
                and request.form.get('confirm_past_date') != payload['parsed_date'].isoformat()):
            return render_template('confirm_past_visit.html', visit=payload)
        with db() as connection:
            connection.execute(
                'INSERT INTO visits (visit_date, visit_time, client, notes, visit_type, equipment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (payload['visit_date'], payload['visit_time'], payload['client'], payload['notes'], payload['visit_type'], payload['equipment'], datetime.now().isoformat(timespec='seconds')),
            )
        return redirect(f'/admin/?month={payload["parsed_date"].strftime("%Y-%m")}&saved=1')

    @app.get('/admin/visitas/<int:visit_id>')
    def visit_detail(visit_id):
        visit = db().execute('SELECT * FROM visits WHERE id = ?', (visit_id,)).fetchone()
        if not visit:
            abort(404)
        return render_template('visit.html', visit=visit, error=None)

    @app.post('/admin/visitas/<int:visit_id>/editar')
    def edit_visit(visit_id):
        existing = db().execute('SELECT * FROM visits WHERE id = ?', (visit_id,)).fetchone()
        if not existing:
            abort(404)
        payload, error = visit_payload()
        if error:
            return render_template('visit.html', visit={**dict(existing), **request.form}, error=error), 400
        with db() as connection:
            connection.execute(
                'UPDATE visits SET visit_date = ?, visit_time = ?, client = ?, notes = ?, visit_type = ?, equipment = ? WHERE id = ?',
                (payload['visit_date'], payload['visit_time'], payload['client'], payload['notes'], payload['visit_type'], payload['equipment'], visit_id),
            )
        return redirect(f'/admin/visitas/{visit_id}?saved=1')

    @app.post('/admin/visitas/<int:visit_id>/excluir')
    def delete_visit(visit_id):
        with db() as connection:
            deleted = connection.execute('DELETE FROM visits WHERE id = ?', (visit_id,)).rowcount
        if not deleted:
            abort(404)
        return redirect('/admin/?deleted=1')

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
