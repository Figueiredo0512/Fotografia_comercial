"""Servidor local: site público e administração com senha + código por e-mail."""
import argparse
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from contextlib import closing
from datetime import timedelta
from email.message import EmailMessage

from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT.parent / '.fotografia-admin'
CODE_LIFETIME = 600
SESSION_LIFETIME = 3600
MAX_ATTEMPTS = 5
PUBLIC_FILES = {'styles.css', 'admin.css'}


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
        MAX_CONTENT_LENGTH=8192, MAX_FORM_PARTS=20,
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

    def authenticated():
        token = session.get('auth', '')
        if not token:
            return False
        row = db().execute('SELECT expires FROM sessions WHERE token_hash = ?', (digest(token),)).fetchone()
        if row and row['expires'] > now():
            g.auth_expires = row['expires']
            return True
        session.pop('auth', None)
        return False

    def login_limit(email):
        # Quotas persistem entre reinícios e não dependem de cookies do navegador.
        buckets = [(f'ip:{request.remote_addr}', 10), (f'email:{digest(email)}', 5)]
        with db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM attempts WHERE at < ?', (now() - 900,))
            connection.execute('DELETE FROM challenges WHERE expires < ?', (now(),))
            connection.execute('DELETE FROM sessions WHERE expires < ?', (now(),))
            for bucket, limit in buckets:
                count = connection.execute('SELECT count(*) FROM attempts WHERE bucket = ?', (bucket,)).fetchone()[0]
                if count >= limit:
                    return False
            for bucket, _limit in buckets:
                connection.execute('INSERT INTO attempts VALUES (?, ?)', (bucket, now()))
        return True

    def send_code(email, code):
        # Substituição de transporte só existe em testes automatizados.
        if app.testing and app.config['SEND_CODE']:
            app.config['SEND_CODE'](email, code)
            return
        config = app.config['SMTP']
        if config is None:
            smtp_path = data / 'smtp.json'
            config = json.loads(smtp_path.read_text()) if smtp_path.exists() else {}
        required = ['host', 'port', 'username', 'password', 'sender']
        if not all(config.get(field) for field in required):
            raise RuntimeError('SMTP não configurado')
        message = EmailMessage()
        message['From'] = config['sender']
        message['To'] = email
        message['Subject'] = 'Seu código de acesso — Fotografia gastronômica'
        message.set_content(
            f'Seu código de acesso é: {code}\n\n'
            'Ele expira em até 10 minutos e só pode ser usado uma vez.\n'
            'Se você não solicitou este acesso, ignore esta mensagem.\n'
        )
        context = ssl.create_default_context()
        smtp_password = config['password']
        # O Gmail exibe senhas de app em quatro grupos; os espaços são apenas formatação.
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

    def login_page(error=None, status=200, email=''):
        return render_template('login.html', error=error, email=email), status

    @app.get('/')
    @app.get('/index.html')
    def home():
        return app.response_class((ROOT / 'index.html').read_text(), mimetype='text/html')

    @app.get('/<filename>')
    def asset(filename):
        if filename not in PUBLIC_FILES:
            abort(404)
        return app.response_class((ROOT / filename).read_text(), mimetype='text/css')

    @app.route('/admin/login', methods=['GET', 'POST'])
    def login():
        if authenticated():
            return redirect(url_for('dashboard'))
        if request.method == 'GET':
            return login_page()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if len(email) > 254 or len(password) > 256:
            return login_page('E-mail ou senha incorretos.', 401)
        if not login_limit(email):
            return login_page('Muitas tentativas. Aguarde 15 minutos e tente novamente.', 429, email)
        admin = db().execute('SELECT * FROM admin WHERE id = 1').fetchone()
        correct = check_password_hash(admin['password_hash'] if admin else dummy_hash, password)
        if not admin or not correct or email != admin['email']:
            return login_page('E-mail ou senha incorretos.', 401, email)
        challenge = secrets.token_urlsafe(32)
        code = f'{secrets.randbelow(1000000):06d}'
        try:
            with db() as connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute('DELETE FROM challenges')
                connection.execute(
                    'INSERT INTO challenges (id, code_hash, expires, last_send) VALUES (?, ?, ?, ?)',
                    (challenge, code_digest(challenge, code), now() + CODE_LIFETIME, now()),
                )
                send_code(admin['email'], code)
        except (smtplib.SMTPException, OSError, RuntimeError, ValueError):
            app.logger.warning('Não foi possível enviar o código de acesso. Confira a configuração SMTP.')
            return login_page('Não foi possível enviar o código. Verifique a configuração de e-mail do administrador.', 503, email)
        session.clear()
        session['pending'] = challenge
        csrf()
        return redirect(url_for('verify'), code=303)

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
                    connection.execute('INSERT INTO sessions VALUES (?, ?)', (digest(token), now() + SESSION_LIFETIME))
                    session.clear()
                    session.permanent = True
                    session['auth'] = token
                    csrf()
                    return redirect(url_for('dashboard'), code=303)
        admin = db().execute('SELECT email FROM admin WHERE id = 1').fetchone()
        return render_template('verify.html', email=admin['email'], error=error, sent=request.args.get('sent') == '1'), status

    @app.post('/admin/reenviar')
    def resend():
        challenge_id = session.get('pending', '')
        with db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM challenges WHERE id = ?', (challenge_id,)).fetchone()
            if not row or row['expires'] <= now() or row['attempts'] >= MAX_ATTEMPTS:
                session.pop('pending', None)
                return login_page('O código expirou. Entre novamente.', 401)
            admin = connection.execute('SELECT email FROM admin WHERE id = 1').fetchone()
            if now() - row['last_send'] < 60 or row['sends'] >= 3:
                return render_template('verify.html', email=admin['email'], error='Aguarde um minuto entre envios. São permitidos até três envios por acesso.'), 429
            code = f'{secrets.randbelow(1000000):06d}'
            try:
                send_code(admin['email'], code)
            except (smtplib.SMTPException, OSError, RuntimeError, ValueError):
                return render_template('verify.html', email=admin['email'], error='Não foi possível reenviar. O código anterior continua válido até expirar.'), 503
            # Reenviar não zera tentativas nem estende o prazo total do desafio.
            connection.execute('UPDATE challenges SET code_hash = ?, last_send = ?, sends = sends + 1 WHERE id = ?', (code_digest(challenge_id, code), now(), challenge_id))
        return redirect(url_for('verify', sent='1'), code=303)

    @app.get('/admin')
    @app.get('/admin/')
    def dashboard():
        if not authenticated():
            return redirect(url_for('login'))
        admin = db().execute('SELECT email FROM admin WHERE id = 1').fetchone()
        return render_template('dashboard.html', email=admin['email'])

    @app.post('/admin/sair')
    def logout():
        with db() as connection:
            connection.execute('DELETE FROM sessions WHERE token_hash = ?', (digest(session.get('auth', '')),))
            connection.execute('DELETE FROM challenges WHERE id = ?', (session.get('pending', ''),))
        session.clear()
        return redirect(url_for('login'), code=303)

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
            password = getpass.getpass('Nova senha do painel (mínimo 12 caracteres): ')
            if not 12 <= len(password) <= 256:
                parser.error('A senha deve ter de 12 a 256 caracteres.')
            if password != getpass.getpass('Repita a senha: '):
                parser.error('As senhas não coincidem.')
            connection.execute('INSERT OR REPLACE INTO admin VALUES (1, ?, ?)', (email, generate_password_hash(password, method='scrypt')))
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
        private_write(Path(app.config['DATA_DIR']) / 'smtp.json', json.dumps(dict(host=host, port=port, security=security, username=username, sender=sender, password=password)))
        print('Configuração salva fora do repositório. Será usada no próximo acesso.')


if __name__ == '__main__':
    main()
