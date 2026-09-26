"""Servidor local: site público e administração com senha + código por e-mail."""
import argparse
import calendar
import getpass
import hashlib
import json
from zoneinfo import ZoneInfo
from datetime import date, datetime, timedelta
import hmac
import os
from pathlib import Path
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from contextlib import closing
from email.message import EmailMessage

from flask import Flask, abort, g, redirect, render_template, render_template_string, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT.parent / '.fotografia-admin'
PUBLIC_FILES = {'styles.css', 'admin.css', 'carousel.js', 'calendar.js'}
CODE_LIFETIME = 600
SESSION_LIFETIME = 3600
MAX_ATTEMPTS = 5


def private_write(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)


def valid_email(value):
    return len(value) <= 254 and bool(re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value))


def create_app(test_config=None):
    app = Flask(__name__, static_folder=None, template_folder=str(ROOT / 'templates'))
    app.config.update(
        DATA_DIR=str(DATA_DIR), SECRET_KEY=None,
        SESSION_COOKIE_NAME='fg_admin', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
        MAX_CONTENT_LENGTH=12 * 1024 * 1024, MAX_FORM_PARTS=20,
        TRUSTED_HOSTS=['localhost', '127.0.0.1'],
        SMTP=None, SEND_CODE=None, NOW=time.time,
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
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                city TEXT NOT NULL,
                created_at TEXT NOT NULL
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
        photo_columns = {row[1] for row in db.execute('PRAGMA table_info(portfolio_images)')}
        challenge_columns = {row[1] for row in db.execute('PRAGMA table_info(challenges)')}
        session_columns = {row[1] for row in db.execute('PRAGMA table_info(sessions)')}
        if 'email' not in challenge_columns:
            db.execute("ALTER TABLE challenges ADD COLUMN email TEXT NOT NULL DEFAULT ''")
        if 'purpose' not in challenge_columns:
            db.execute("ALTER TABLE challenges ADD COLUMN purpose TEXT NOT NULL DEFAULT 'login'")
        if 'email' not in session_columns:
            db.execute("ALTER TABLE sessions ADD COLUMN email TEXT NOT NULL DEFAULT ''")
        if 'hidden' not in photo_columns:
            db.execute('ALTER TABLE portfolio_images ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0')
        if 'visit_type' not in columns:
            db.execute("ALTER TABLE visits ADD COLUMN visit_type TEXT NOT NULL DEFAULT 'reuniao'")
        if 'equipment' not in columns:
            db.execute("ALTER TABLE visits ADD COLUMN equipment TEXT NOT NULL DEFAULT ''")
        legacy_admin = db.execute('SELECT email, password_hash FROM admin WHERE id = 1').fetchone()
        if legacy_admin:
            db.execute(
                '''INSERT OR IGNORE INTO users
                   (first_name, last_name, email, password_hash, city, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('Administrador', '', legacy_admin[0], legacy_admin[1], 'A definir', datetime.now().isoformat(timespec='seconds')),
            )
    os.chmod(db_path, 0o600)
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(db_path, timeout=25)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        if 'db' in g:
            g.db.close()

    def now():
        return app.config['NOW']()

    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def code_digest(challenge, code):
        key = app.config['SECRET_KEY'].encode()
        return hmac.new(key, f'{challenge}:{code}'.encode(), hashlib.sha256).hexdigest()

    def csrf():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return session['csrf']

    app.jinja_env.globals['csrf_token'] = csrf

    def authenticated():
        token = session.get('auth', '')
        if not token:
            return False
        row = db().execute('SELECT expires, email FROM sessions WHERE token_hash = ?', (digest(token),)).fetchone()
        if row and row['expires'] > now():
            g.user_email = row['email']
            return True
        session.pop('auth', None)
        return False

    @app.context_processor
    def authentication_context():
        return {'admin_authenticated': bool(getattr(g, 'admin_authenticated', False))}

    @app.before_request
    def protect_requests():
        if request.path.startswith('/admin'):
            g.admin_authenticated = authenticated()
            public_endpoints = {
                'asset', 'login', 'register', 'verify', 'resend',
                'forgot_password', 'reset_password',
            }
            if request.endpoint not in public_endpoints and not g.admin_authenticated:
                return redirect(url_for('login'))
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
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        if request.path.startswith('/admin'):
            response.headers['Cache-Control'] = 'no-store, private'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    def login_limit(email):
        buckets = [(f'ip:{request.remote_addr}', 10), (f'email:{digest(email)}', 5)]
        with db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM attempts WHERE at < ?', (now() - 900,))
            connection.execute('DELETE FROM challenges WHERE expires < ?', (now(),))
            connection.execute('DELETE FROM sessions WHERE expires < ?', (now(),))
            for bucket, limit in buckets:
                if connection.execute('SELECT count(*) FROM attempts WHERE bucket = ?', (bucket,)).fetchone()[0] >= limit:
                    return False
            for bucket, _limit in buckets:
                connection.execute('INSERT INTO attempts VALUES (?, ?)', (bucket, now()))
        return True

    def password_reset_limit(email):
        bucket = f'reset:{digest(email)}'
        with db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM attempts WHERE at < ?', (now() - 900,))
            count = connection.execute('SELECT count(*) FROM attempts WHERE bucket = ?', (bucket,)).fetchone()[0]
            if count >= 3:
                return False
            connection.execute('INSERT INTO attempts VALUES (?, ?)', (bucket, now()))
        return True

    def send_code(email, code, purpose='login'):
        if app.testing and app.config['SEND_CODE']:
            app.config['SEND_CODE'](email, code)
            return
        config = app.config['SMTP']
        if config is None:
            smtp_path = data / 'smtp.json'
            config = json.loads(smtp_path.read_text()) if smtp_path.exists() else {}
        if not all(config.get(field) for field in ('host', 'port', 'username', 'password', 'sender')):
            raise RuntimeError('SMTP não configurado')
        message = EmailMessage()
        message['From'] = config['sender']
        message['To'] = email
        action = 'redefinição de senha' if purpose == 'reset' else 'acesso'
        message['Subject'] = f'Seu código de {action} — Fotografia gastronômica'
        message.set_content(
            f'Seu código de {action} é: {code}\n\n'
            'Ele expira em até 10 minutos e só pode ser usado uma vez.\n'
            'Se você não solicitou este acesso, ignore esta mensagem.\n'
        )
        context = ssl.create_default_context()
        smtp_password = config['password']
        if str(config.get('host', '')).lower() == 'smtp.gmail.com':
            smtp_password = ''.join(str(smtp_password).split())
        if config.get('security') == 'ssl':
            with smtplib.SMTP_SSL(config['host'], int(config['port']), timeout=15, context=context) as smtp:
                smtp.login(config['username'], smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(config['host'], int(config['port']), timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(config['username'], smtp_password)
                smtp.send_message(message)

    def email_delivery_error(error):
        if isinstance(error, smtplib.SMTPAuthenticationError):
            return ('O Gmail recusou a credencial de envio. Configure uma senha de app do Google; '
                    'a senha normal da conta não funciona.')
        if isinstance(error, (json.JSONDecodeError, RuntimeError, ValueError)):
            return 'A configuração de e-mail está incompleta ou inválida. Configure o envio novamente.'
        return 'Não foi possível conectar ao serviço de e-mail. Tente novamente em alguns minutos.'

    def login_page(error=None, status=200, email='', message=None):
        return render_template('login.html', error=error, email=email, message=message), status

    def registration_page(error=None, status=200, values=None):
        return render_template('register.html', error=error, values=values or {}), status

    def forgot_password_page(error=None, status=200, email=''):
        return render_template('forgot_password.html', error=error, email=email), status

    def reset_password_page(error=None, status=200):
        return render_template('reset_password.html', error=error), status

    @app.get('/')
    @app.get('/index.html')
    def home():
        images = db().execute(
            'SELECT filename, title, description FROM portfolio_images WHERE hidden = 0 ORDER BY id DESC LIMIT 5'
        ).fetchall()
        return render_template_string((ROOT / 'index.html').read_text(), portfolio_images=images)

    @app.get('/portfolio')
    def public_portfolio():
        images = db().execute(
            'SELECT filename, title, description FROM portfolio_images WHERE hidden = 0 ORDER BY id DESC'
        ).fetchall()
        return render_template('public_portfolio.html', images=images)

    @app.get('/<filename>')
    def asset(filename):
        if filename not in PUBLIC_FILES:
            abort(404)
        mime = 'text/javascript' if filename.endswith('.js') else 'text/css'
        return app.response_class((ROOT / filename).read_text(), mimetype=mime)

    @app.route('/admin/login', methods=['GET', 'POST'])
    def login():
        if authenticated():
            return redirect(url_for('dashboard'))
        if request.method == 'GET':
            message = None
            if request.args.get('registered') == '1':
                message = 'Cadastro concluído. Entre para receber seu código de acesso.'
            elif request.args.get('reset') == '1':
                message = 'Senha redefinida. Entre com a nova senha.'
            return login_page(message=message)
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if len(email) > 254 or len(password) > 256 or not login_limit(email):
            return login_page('E-mail ou senha incorretos, ou muitas tentativas seguidas.', 401, email)
        user = db().execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        correct = check_password_hash(user['password_hash'] if user else dummy_hash, password)
        if not user or not correct:
            return login_page('E-mail ou senha incorretos.', 401, email)
        challenge = secrets.token_urlsafe(32)
        code = f'{secrets.randbelow(1000000):06d}'
        try:
            with db() as connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute('DELETE FROM challenges WHERE email = ?', (user['email'],))
                connection.execute(
                    'INSERT INTO challenges (id, code_hash, expires, last_send, email) VALUES (?, ?, ?, ?, ?)',
                    (challenge, code_digest(challenge, code), now() + CODE_LIFETIME, now(), user['email']),
                )
                send_code(user['email'], code)
        except (smtplib.SMTPException, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            app.logger.warning('Falha no envio do código de acesso: %s.', type(error).__name__)
            return login_page(email_delivery_error(error), 503, email)
        session.clear()
        session['pending'] = challenge
        csrf()
        return redirect(url_for('verify'), code=303)

    @app.route('/admin/cadastro', methods=['GET', 'POST'])
    def register():
        if authenticated():
            return redirect(url_for('dashboard'))
        if request.method == 'GET':
            return registration_page()
        values = {
            'first_name': request.form.get('first_name', '').strip(),
            'last_name': request.form.get('last_name', '').strip(),
            'email': request.form.get('email', '').strip().lower(),
            'email_confirmation': request.form.get('email_confirmation', '').strip().lower(),
            'city': request.form.get('city', '').strip(),
        }
        password = request.form.get('password', '')
        password_confirmation = request.form.get('password_confirmation', '')
        if not all(values.values()):
            return registration_page('Preencha todos os campos.', 400, values)
        if any(len(values[field]) > 100 for field in ('first_name', 'last_name', 'city')):
            return registration_page('Nome, sobrenome e cidade devem ter até 100 caracteres.', 400, values)
        if not valid_email(values['email']) or values['email'] != values['email_confirmation']:
            return registration_page('Os e-mails informados precisam ser válidos e iguais.', 400, values)
        if not 8 <= len(password) <= 256 or password != password_confirmation:
            return registration_page('As senhas precisam ser iguais e ter pelo menos 8 caracteres.', 400, values)
        try:
            with db() as connection:
                connection.execute(
                    '''INSERT INTO users
                       (first_name, last_name, email, password_hash, city, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (values['first_name'], values['last_name'], values['email'],
                     generate_password_hash(password, method='scrypt'), values['city'],
                     datetime.now().isoformat(timespec='seconds')),
                )
        except sqlite3.IntegrityError:
            return registration_page('Já existe uma conta cadastrada com este e-mail.', 409, values)
        return redirect(url_for('login', registered='1'), code=303)

    @app.route('/admin/esqueci-senha', methods=['GET', 'POST'])
    def forgot_password():
        if authenticated():
            return redirect(url_for('dashboard'))
        if request.method == 'GET':
            return forgot_password_page()
        email = request.form.get('email', '').strip().lower()
        if not valid_email(email):
            return forgot_password_page('Informe um e-mail válido.', 400, email)
        user = db().execute('SELECT email FROM users WHERE email = ?', (email,)).fetchone()
        if not user:
            return forgot_password_page('Não encontramos um cadastro com este e-mail.', 404, email)
        if not password_reset_limit(email):
            return forgot_password_page('Muitas solicitações. Aguarde 15 minutos e tente novamente.', 429, email)
        challenge = secrets.token_urlsafe(32)
        code = f'{secrets.randbelow(1000000):06d}'
        try:
            with db() as connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute("DELETE FROM challenges WHERE email = ? AND purpose = 'reset'", (user['email'],))
                connection.execute(
                    '''INSERT INTO challenges
                       (id, code_hash, expires, last_send, email, purpose)
                       VALUES (?, ?, ?, ?, ?, 'reset')''',
                    (challenge, code_digest(challenge, code), now() + CODE_LIFETIME, now(), user['email']),
                )
                send_code(user['email'], code, purpose='reset')
        except (smtplib.SMTPException, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            app.logger.warning('Falha no envio do código de redefinição: %s.', type(error).__name__)
            return forgot_password_page(email_delivery_error(error), 503, email)
        session.clear()
        session['pending_reset'] = challenge
        csrf()
        return redirect(url_for('reset_password'), code=303)

    @app.route('/admin/redefinir-senha', methods=['GET', 'POST'])
    def reset_password():
        challenge_id = session.get('pending_reset', '')
        row = db().execute(
            "SELECT * FROM challenges WHERE id = ? AND purpose = 'reset'", (challenge_id,)
        ).fetchone()
        if not row or row['expires'] <= now() or row['attempts'] >= MAX_ATTEMPTS:
            session.pop('pending_reset', None)
            return forgot_password_page('O código expirou. Solicite uma nova redefinição.', 401)
        if request.method == 'GET':
            return reset_password_page()
        code = request.form.get('code', '').strip()
        password = request.form.get('password', '')
        password_confirmation = request.form.get('password_confirmation', '')
        if not hmac.compare_digest(code_digest(challenge_id, code), row['code_hash']):
            with db() as connection:
                connection.execute('UPDATE challenges SET attempts = attempts + 1 WHERE id = ?', (challenge_id,))
            return reset_password_page('Código inválido. Confira o e-mail e tente novamente.', 401)
        if not 8 <= len(password) <= 256 or password != password_confirmation:
            return reset_password_page('As senhas precisam ser iguais e ter pelo menos 8 caracteres.', 400)
        password_hash = generate_password_hash(password, method='scrypt')
        with db() as connection:
            connection.execute('UPDATE users SET password_hash = ? WHERE email = ?', (password_hash, row['email']))
            connection.execute('UPDATE admin SET password_hash = ? WHERE email = ?', (password_hash, row['email']))
            connection.execute('DELETE FROM sessions WHERE email = ?', (row['email'],))
            connection.execute('DELETE FROM challenges WHERE id = ?', (challenge_id,))
        session.clear()
        csrf()
        return redirect(url_for('login', reset='1'), code=303)

    @app.route('/admin/verificar', methods=['GET', 'POST'])
    def verify():
        challenge_id = session.get('pending', '')
        error = None
        status = 200
        with db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM challenges WHERE id = ?', (challenge_id,)).fetchone()
            if not row or row['expires'] <= now() or row['attempts'] >= MAX_ATTEMPTS:
                session.pop('pending', None)
                return login_page('O código expirou ou atingiu o limite de tentativas. Entre novamente.', 401)
            if request.method == 'POST':
                code = request.form.get('code', '').strip()
                if not hmac.compare_digest(code_digest(challenge_id, code), row['code_hash']):
                    connection.execute('UPDATE challenges SET attempts = attempts + 1 WHERE id = ?', (challenge_id,))
                    error = 'Código inválido. Confira o e-mail e tente novamente.'
                    status = 401
                    if row['attempts'] + 1 >= MAX_ATTEMPTS:
                        connection.execute('DELETE FROM challenges WHERE id = ?', (challenge_id,))
                        session.pop('pending', None)
                        return login_page('Limite de tentativas atingido. Entre novamente.', 401)
                else:
                    connection.execute('DELETE FROM challenges WHERE id = ?', (challenge_id,))
                    token = secrets.token_urlsafe(32)
                    connection.execute(
                        'INSERT INTO sessions (token_hash, expires, email) VALUES (?, ?, ?)',
                        (digest(token), now() + SESSION_LIFETIME, row['email']),
                    )
                    session.clear()
                    session.permanent = True
                    session['auth'] = token
                    csrf()
                    return redirect(url_for('dashboard'), code=303)
        return render_template('verify.html', email=row['email'], error=error, sent=request.args.get('sent') == '1'), status

    @app.post('/admin/reenviar')
    def resend():
        challenge_id = session.get('pending', '')
        with db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM challenges WHERE id = ?', (challenge_id,)).fetchone()
            if not row or row['expires'] <= now() or row['attempts'] >= MAX_ATTEMPTS:
                session.pop('pending', None)
                return login_page('O código expirou. Entre novamente.', 401)
            if now() - row['last_send'] < 60 or row['sends'] >= 3:
                return render_template('verify.html', email=row['email'], error='Aguarde um minuto entre envios. São permitidos até três envios por acesso.'), 429
            code = f'{secrets.randbelow(1000000):06d}'
            try:
                send_code(row['email'], code)
            except (smtplib.SMTPException, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                return render_template('verify.html', email=row['email'], error=email_delivery_error(error)), 503
            connection.execute(
                'UPDATE challenges SET code_hash = ?, last_send = ?, sends = sends + 1 WHERE id = ?',
                (code_digest(challenge_id, code), now(), challenge_id),
            )
        return redirect(url_for('verify', sent='1'), code=303)

    @app.get('/admin')
    @app.get('/admin/')
    def dashboard():
        admin = db().execute('SELECT email FROM users WHERE email = ?', (g.user_email,)).fetchone()
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

    @app.post('/admin/sair')
    def logout():
        with db() as connection:
            connection.execute('DELETE FROM sessions WHERE token_hash = ?', (digest(session.get('auth', '')),))
            connection.execute('DELETE FROM challenges WHERE id = ?', (session.get('pending', ''),))
        session.clear()
        return redirect(url_for('login'), code=303)

    def portfolio_page(error=None, status=200):
        images = db().execute(
            'SELECT id, filename, title, description, created_at, hidden FROM portfolio_images ORDER BY id DESC'
        ).fetchall()
        message = 'Foto adicionada ao portfólio.' if request.args.get('saved') == '1' else None
        if request.args.get('deleted') == '1':
            message = 'Foto excluída.'
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
        try:
            filename, mime_type = store_photo(upload)
        except ValueError as error:
            return portfolio_page(str(error), 400)
        target = portfolio_dir / filename
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

    def store_photo(upload):
        header = upload.stream.read(16)
        upload.stream.seek(0)
        signatures = (
            (header.startswith(b'\xff\xd8\xff'), '.jpg', 'image/jpeg'),
            (header.startswith(b'\x89PNG\r\n\x1a\n'), '.png', 'image/png'),
            (header.startswith(b'RIFF') and header[8:12] == b'WEBP', '.webp', 'image/webp'),
        )
        detected = next(((extension, mime) for valid, extension, mime in signatures if valid), None)
        if not detected:
            raise ValueError('O arquivo precisa ser uma imagem JPEG, PNG ou WebP válida.')
        extension, mime_type = detected
        filename = f'{secrets.token_hex(16)}{extension}'
        target = portfolio_dir / filename
        upload.save(target)
        os.chmod(target, 0o600)
        return filename, mime_type

    def find_photo(image_id):
        photo = db().execute('SELECT * FROM portfolio_images WHERE id = ?', (image_id,)).fetchone()
        if photo is None:
            abort(404)
        return dict(photo)

    @app.route('/admin/portfolio/<int:image_id>/editar', methods=['GET', 'POST'])
    def edit_photo(image_id):
        photo = find_photo(image_id)
        if request.method == 'GET':
            return render_template('edit_photo.html', photo=photo)
        values = dict(photo, title=request.form.get('title', '').strip(),
                      description=request.form.get('description', '').strip(),
                      hidden=int(request.form.get('hidden') == '1'))
        if not values['title'] or len(values['title']) > 120 or len(values['description']) > 500:
            return render_template('edit_photo.html', photo=values, error='Informe um título de até 120 caracteres e uma descrição de até 500.'), 400
        upload = request.files.get('image')
        replacement = None
        if upload and upload.filename:
            try:
                replacement = store_photo(upload)
            except ValueError as error:
                return render_template('edit_photo.html', photo=values, error=str(error)), 400
        filename, mime = replacement or (photo['filename'], photo['mime_type'])
        try:
            with db() as connection:
                connection.execute('UPDATE portfolio_images SET title=?, description=?, hidden=?, filename=?, mime_type=? WHERE id=?',
                                   (values['title'], values['description'], values['hidden'], filename, mime, image_id))
        except sqlite3.Error:
            if replacement:
                (portfolio_dir / filename).unlink(missing_ok=True)
            raise
        if replacement:
            (portfolio_dir / photo['filename']).unlink(missing_ok=True)
        return redirect(f'/admin/portfolio/{image_id}/editar?saved=1', code=303)

    @app.route('/admin/portfolio/<int:image_id>/excluir', methods=['GET', 'POST'])
    def delete_photo(image_id):
        photo = find_photo(image_id)
        if request.method == 'GET':
            return render_template('delete_photo.html', photo=photo)
        if request.form.get('confirm_delete') != '1':
            abort(400)
        with db() as connection:
            connection.execute('DELETE FROM portfolio_images WHERE id=?', (image_id,))
        (portfolio_dir / photo['filename']).unlink(missing_ok=True)
        return redirect('/admin/portfolio?deleted=1', code=303)

    @app.get('/portfolio/imagens/<filename>')
    @app.get('/admin/portfolio/imagens/<filename>')
    def portfolio_image(filename):
        image = db().execute('SELECT mime_type, hidden FROM portfolio_images WHERE filename = ?', (filename,)).fetchone()
        target = portfolio_dir / filename
        if not image or not target.is_file() or target.parent != portfolio_dir:
            abort(404)
        if image['hidden'] and not request.path.startswith('/admin/'):
            abort(404)
        response = send_file(target, mimetype=image['mime_type'], conditional=True)
        response.headers['Cache-Control'] = 'no-store, private'
        return response

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
            admin = db().execute('SELECT email FROM users WHERE email = ?', (g.user_email,)).fetchone()
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
    setup = sub.add_parser('init-admin')
    setup.add_argument('--email', required=True)
    sub.add_parser('configure-email')
    sub.add_parser('reset-password')
    args = parser.parse_args()
    app = create_app()
    database = Path(app.config['DATA_DIR']) / 'admin.sqlite3'
    if args.command == 'serve':
        app.run(host='127.0.0.1', port=args.port, debug=False)
    elif args.command in ('init-admin', 'reset-password'):
        with closing(sqlite3.connect(database)) as connection, connection:
            existing = connection.execute('SELECT email FROM admin WHERE id = 1').fetchone()
            if args.command == 'init-admin' and existing:
                parser.error('Administrador já cadastrado. Use reset-password para trocar a senha.')
            if args.command == 'reset-password' and not existing:
                parser.error('Cadastre o administrador com init-admin primeiro.')
            email = existing[0] if existing else args.email.strip().lower()
            if not valid_email(email):
                parser.error('Informe um e-mail válido.')
            password = getpass.getpass('Nova senha do painel (mínimo 8 caracteres): ')
            if not 8 <= len(password) <= 256:
                parser.error('A senha deve ter de 8 a 256 caracteres.')
            if password != getpass.getpass('Repita a senha: '):
                parser.error('As senhas não coincidem.')
            connection.execute(
                'INSERT OR REPLACE INTO admin VALUES (1, ?, ?)',
                (email, generate_password_hash(password, method='scrypt')),
            )
            password_hash = connection.execute('SELECT password_hash FROM admin WHERE id = 1').fetchone()[0]
            existing_user = connection.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            if existing_user:
                connection.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, existing_user[0]))
            else:
                connection.execute(
                    '''INSERT INTO users
                       (first_name, last_name, email, password_hash, city, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    ('Administrador', '', email, password_hash, 'A definir', datetime.now().isoformat(timespec='seconds')),
                )
            connection.execute('DELETE FROM sessions')
            connection.execute('DELETE FROM challenges')
        print('Administrador configurado. A senha foi armazenada como hash; sessões anteriores foram encerradas.')
    else:
        print('Configuração SMTP local. Nenhum e-mail será enviado nesta etapa.')
        host = input('Servidor SMTP (ex.: smtp.gmail.com): ').strip()
        port = int(input('Porta (587 para STARTTLS, 465 para SSL): ').strip())
        security = 'ssl' if port == 465 else 'starttls'
        username = input('Usuário SMTP: ').strip()
        sender = input('E-mail remetente: ').strip()
        password = getpass.getpass('Senha de app/credencial SMTP (não é a senha do painel): ')
        if host.lower() == 'smtp.gmail.com':
            password = ''.join(password.split())
        if not host or port not in range(1, 65536) or not username or not password or not valid_email(sender):
            parser.error('Configuração incompleta ou inválida.')
        private_write(
            Path(app.config['DATA_DIR']) / 'smtp.json',
            json.dumps(dict(host=host, port=port, security=security, username=username, sender=sender, password=password)),
        )
        print('Configuração salva fora do repositório. Será usada no próximo acesso.')


if __name__ == '__main__':
    main()
