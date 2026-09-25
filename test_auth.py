"""Testes isolados: transporte de e-mail simulado, sem enviar mensagens reais."""
import re
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager, closing
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from server import create_app


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = 'senha-de-teste-longa-123'
        cls.password_hash = generate_password_hash(cls.password, method='scrypt')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = [1000000.0]
        self.mailbox = []
        self.config = {
            'TESTING': True, 'SECRET_KEY': 'isolated-test-key-not-used-by-server',
            'DATA_DIR': self.directory.name,
            'NOW': lambda: self.clock[0],
            'SEND_CODE': lambda email, code: self.mailbox.append((email, code)),
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        with self.database() as db:
            db.execute('INSERT INTO admin VALUES (1, ?, ?)', ('admin@example.test', self.password_hash))

    @contextmanager
    def database(self):
        with closing(sqlite3.connect(Path(self.directory.name) / 'admin.sqlite3')) as connection, connection:
            yield connection

    def csrf(self, client=None):
        with (client or self.client).session_transaction() as session:
            return session['csrf']

    def login(self, client=None, password=None, email='admin@example.test'):
        client = client or self.client
        client.get('/admin/login')
        return client.post('/admin/login', data={
            'csrf_token': self.csrf(client), 'email': email,
            'password': password if password is not None else self.password,
        })

    def verify(self, code=None):
        return self.client.post('/admin/verificar', data={
            'csrf_token': self.csrf(),
            'code': code if code is not None else self.mailbox[-1][1],
        })

    def test_password_alone_does_not_open_dashboard(self):
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        result = self.login()
        self.assertEqual(result.status_code, 303)
        self.assertEqual(result.location, '/admin/verificar')
        self.assertEqual(self.mailbox[0][0], 'admin@example.test')
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.assertNotIn(self.mailbox[0][1].encode(), result.data)
        self.assertEqual(self.verify().status_code, 303)
        dashboard = self.client.get('/admin/')
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b'admin@example.test', dashboard.data)
        self.assertIn('no-store', dashboard.headers['Cache-Control'])

    def test_login_has_only_email_and_password_visible_inputs(self):
        page = self.client.get('/admin/login').text
        fields = re.findall(r'<input[^>]+type="(?!hidden)([^"]+)"', page)
        self.assertEqual(fields, ['email', 'password'])

    def test_wrong_password_and_unknown_email_are_generic_and_send_nothing(self):
        wrong = self.login(password='incorreta')
        unknown = self.login(email='unknown@example.test')
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertIn('E-mail ou senha incorretos.', wrong.text)
        self.assertIn('E-mail ou senha incorretos.', unknown.text)
        self.assertEqual(self.mailbox, [])

    def test_code_is_single_use_and_browser_bound(self):
        self.login()
        with self.client.session_transaction() as session:
            old_session = dict(session)
        other = self.app.test_client()
        other.get('/admin/login')
        self.assertEqual(other.post('/admin/verificar', data={'csrf_token': self.csrf(other), 'code': self.mailbox[-1][1]}).status_code, 401)
        self.assertEqual(self.verify().status_code, 303)
        with other.session_transaction() as session:
            session.clear()
            session.update(old_session)
        self.assertEqual(other.post('/admin/verificar', data={'csrf_token': self.csrf(other), 'code': self.mailbox[-1][1]}).status_code, 401)

    def test_expired_code_is_rejected(self):
        self.login()
        self.clock[0] += 601
        self.assertEqual(self.verify().status_code, 401)
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_five_wrong_codes_exhaust_challenge(self):
        self.login()
        wrong = '111111' if self.mailbox[-1][1] != '111111' else '222222'
        for _ in range(5):
            self.assertEqual(self.verify(wrong).status_code, 401)
        self.assertEqual(self.verify().status_code, 401)

    def test_resend_invalidates_previous_code_and_has_cooldown(self):
        self.login()
        previous = self.mailbox[-1][1]
        data = {'csrf_token': self.csrf()}
        self.assertEqual(self.client.post('/admin/reenviar', data=data).status_code, 429)
        self.clock[0] += 61
        with patch('server.secrets.randbelow', return_value=123456 if previous != '123456' else 654321):
            self.assertEqual(self.client.post('/admin/reenviar', data=data).status_code, 303)
        self.assertEqual(self.verify(previous).status_code, 401)
        self.assertEqual(self.verify().status_code, 303)

    def test_resend_does_not_reset_attempt_budget(self):
        self.login()
        wrong = '111111' if self.mailbox[-1][1] != '111111' else '222222'
        for _ in range(4):
            self.verify(wrong)
        self.clock[0] += 61
        self.client.post('/admin/reenviar', data={'csrf_token': self.csrf()})
        wrong = '111111' if self.mailbox[-1][1] != '111111' else '222222'
        self.assertEqual(self.verify(wrong).status_code, 401)
        self.assertEqual(self.verify().status_code, 401)

    def test_missing_smtp_never_grants_access(self):
        self.app.config['SEND_CODE'] = None
        self.app.config['SMTP'] = {}
        self.assertEqual(self.login().status_code, 503)
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        with self.database() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM challenges').fetchone()[0], 0)

    def test_smtp_delivery_failure_never_creates_challenge(self):
        def fail(_email, _code):
            raise OSError('test transport failure')
        self.app.config['SEND_CODE'] = fail
        self.assertEqual(self.login().status_code, 503)
        self.assertEqual(self.client.get('/admin/verificar').status_code, 401)

    def test_smtp_uses_tls_and_registered_recipient(self):
        self.app.config['SEND_CODE'] = None
        self.app.config['SMTP'] = {'host': 'smtp.example.test', 'port': 587, 'username': 'sender', 'password': 'test-only', 'sender': 'sender@example.test'}
        with patch('server.smtplib.SMTP') as transport:
            self.assertEqual(self.login().status_code, 303)
            smtp = transport.return_value.__enter__.return_value
            smtp.starttls.assert_called_once()
            message = smtp.send_message.call_args.args[0]
            self.assertEqual(message['To'], 'admin@example.test')
            self.assertRegex(message.get_content(), r'\b\d{6}\b')

    def test_rate_limit_persists_for_a_new_browser_and_server(self):
        for _ in range(5):
            self.assertEqual(self.login(password='incorreta').status_code, 401)
        restarted = create_app(self.config).test_client()
        self.assertEqual(self.login(client=restarted).status_code, 429)

    def test_csrf_protects_login_verify_resend_and_logout(self):
        for path in ['/admin/login', '/admin/verificar', '/admin/reenviar', '/admin/sair']:
            self.assertEqual(self.client.post(path, data={}).status_code, 400)
        self.client.get('/admin/login')
        self.assertEqual(self.client.post('/admin/login', data={'csrf_token': self.csrf()}, headers={'Origin': 'https://attacker.example'}).status_code, 400)

    def test_logout_revokes_even_a_copied_cookie(self):
        self.login()
        self.verify()
        copied = self.client.get_cookie('fg_admin').value
        self.assertEqual(self.client.post('/admin/sair', data={'csrf_token': self.csrf()}).status_code, 303)
        self.client.set_cookie('fg_admin', copied)
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_session_expires(self):
        self.login()
        self.verify()
        self.clock[0] += 3601
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_no_database_source_or_credentials_are_public(self):
        for path in ['/.git/config', '/server.py', '/admin.sqlite3', '/smtp.json', '/.env', '/templates/dashboard.html', '/.venv/pyvenv.cfg', '/../.fotografia-admin/smtp.json']:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/styles.css').status_code, 200)
        self.assertEqual(self.client.get('/admin.css').status_code, 200)

    def test_cookie_and_security_headers(self):
        response = self.client.get('/admin/login')
        cookie = response.headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("form-action 'self'", response.headers['Content-Security-Policy'])


if __name__ == '__main__':
    unittest.main()
