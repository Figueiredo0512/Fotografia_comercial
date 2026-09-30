"""Testes do painel protegido; o envio de e-mail é sempre simulado."""
import sqlite3
import smtplib
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import closing
from pathlib import Path
from werkzeug.security import generate_password_hash

from server import create_app


class AdminPanelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.password = 'senha-de-teste-longa-123'
        self.mailbox = []
        self.app = create_app({
            'TESTING': True,
            'SECRET_KEY': 'isolated-test-key',
            'DATA_DIR': self.directory.name,
            'SEND_CODE': lambda email, code: self.mailbox.append((email, code)),
        })
        self.client = self.app.test_client()
        with closing(sqlite3.connect(Path(self.directory.name) / 'admin.sqlite3')) as db, db:
            password_hash = generate_password_hash(self.password, method='scrypt')
            db.execute('INSERT INTO admin VALUES (1, ?, ?)', ('admin@example.test', password_hash))
            db.execute(
                '''INSERT INTO users
                   (first_name, last_name, email, password_hash, city, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                ('Admin', 'Teste', 'admin@example.test', password_hash, 'Hortolândia', '2026-09-25T00:00:00'),
            )
        self.login_and_verify()

    def csrf(self, client=None):
        with (client or self.client).session_transaction() as session:
            return session['csrf']

    def login_and_verify(self, client=None):
        client = client or self.client
        client.get('/admin/login')
        response = client.post('/admin/login', data={
            'csrf_token': self.csrf(client), 'email': 'admin@example.test', 'password': self.password,
        })
        self.assertEqual(response.status_code, 303)
        response = client.post('/admin/verificar', data={
            'csrf_token': self.csrf(client), 'code': self.mailbox[-1][1],
        })
        self.assertEqual(response.status_code, 303)

    def test_past_event_requires_confirmation_before_persisting(self):
        self.client.get('/admin/')
        past = (datetime.now(ZoneInfo('America/Sao_Paulo')).date() - timedelta(days=1)).isoformat()
        data = dict(csrf_token=self.csrf(), client='Ensaio anterior', visit_date=past,
                    visit_time='15:40', visit_type='ensaio', equipment='R10 e Godox', notes='Comentário preservado')
        response = self.client.post('/admin/visitas', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('DATA PASSADA', response.text)
        with self.database() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM visits').fetchone()[0], 0)
        self.assertIn('R10 e Godox', response.text)
        self.assertEqual(self.client.post('/admin/visitas', data={**data, 'confirm_past_date': '2000-01-01'}).status_code, 200)
        confirmed = self.client.post('/admin/visitas', data={**data, 'confirm_past_date': past})
        self.assertEqual(confirmed.status_code, 302)
        with self.database() as db:
            self.assertEqual(db.execute('SELECT equipment, notes FROM visits').fetchone(), ('R10 e Godox', 'Comentário preservado'))

    def test_today_and_future_do_not_require_confirmation(self):
        self.client.get('/admin/')
        today = datetime.now(ZoneInfo('America/Sao_Paulo')).date()
        for day in [today, today + timedelta(days=1)]:
            result = self.client.post('/admin/visitas', data=dict(csrf_token=self.csrf(), client='Reunião', visit_date=day.isoformat(), visit_time='07:00', visit_type='reuniao'))
            self.assertEqual(result.status_code, 302)

    def database(self):
        return closing(sqlite3.connect(Path(self.directory.name) / 'admin.sqlite3'))

    def test_admin_opens_after_two_step_login(self):
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'admin@example.test', response.data)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_photo_placement_and_hero_replacement(self):
        def upload(title, placement):
            return self.client.post('/admin/portfolio/imagens', data={
                'csrf_token': self.csrf(), 'title': title, 'placement': placement,
                'image': (BytesIO(b'\xff\xd8\xff\xe0test'), 'foto.jpg'),
            })
        self.assertEqual(upload('Galeria teste', 'portfolio').status_code, 302)
        self.assertEqual(upload('Destaque primeiro', 'hero').status_code, 302)
        self.assertIn('Destaque primeiro', self.client.get('/').text)
        self.assertNotIn('Destaque primeiro', self.client.get('/portfolio').text)
        self.assertIn('Galeria teste', self.client.get('/portfolio').text)
        self.assertEqual(upload('Destaque novo', 'hero').status_code, 302)
        with self.database() as db:
            old_id, old_file, hidden = db.execute("SELECT id, filename, hidden FROM portfolio_images WHERE title='Destaque primeiro'").fetchone()
            new_id = db.execute("SELECT id FROM portfolio_images WHERE title='Destaque novo'").fetchone()[0]
        self.assertEqual(hidden, 1)
        self.assertEqual(self.client.get('/portfolio/imagens/' + old_file).status_code, 404)
        self.assertIn('Destaque primeiro', self.client.get('/admin/portfolio').text)
        self.assertNotIn('Destaque primeiro', self.client.get('/').text)
        self.assertEqual(upload('Inválido', 'other').status_code, 400)
        edit = dict(csrf_token=self.csrf(), title='Destaque novo', description='', placement='portfolio')
        self.assertEqual(self.client.post(f'/admin/portfolio/{new_id}/editar', data=edit).status_code, 303)
        self.assertIn('Destaque novo', self.client.get('/portfolio').text)
        self.assertIn('Sua próxima imagem de destaque.', self.client.get('/').text)
        edit.update(title='Restaurada', placement='hero')
        self.assertEqual(self.client.post(f'/admin/portfolio/{old_id}/editar', data=edit).status_code, 303)
        self.assertIn('Restaurada', self.client.get('/').text)
        self.assertNotIn('Restaurada', self.client.get('/portfolio').text)
        edit['hidden'] = '1'
        self.client.post(f'/admin/portfolio/{old_id}/editar', data=edit)
        self.assertIn('Sua próxima imagem de destaque.', self.client.get('/').text)

    def test_portfolio_menu_and_image_upload(self):
        dashboard = self.client.get('/admin/')
        self.assertIn('href="/admin/portfolio"', dashboard.text)
        portfolio = self.client.get('/admin/portfolio')
        self.assertEqual(portfolio.status_code, 200)
        response = self.client.post('/admin/portfolio/imagens', data={
            'csrf_token': self.csrf(), 'title': 'Café especial', 'description': 'Luz lateral',
            'image': (BytesIO(b'\xff\xd8\xff\xe0' + b'foto-de-teste'), 'cafe.jpg'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)
        page = self.client.get('/admin/portfolio')
        self.assertIn('Café especial', page.text)
        self.assertIn('Luz lateral', page.text)
        with self.database() as db:
            filename = db.execute('SELECT filename FROM portfolio_images').fetchone()[0]
        image = self.client.get(f'/admin/portfolio/imagens/{filename}')
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.mimetype, 'image/jpeg')
        self.assertTrue(image.data.startswith(b'\xff\xd8\xff'))
        image.close()
        home = self.client.get('/')
        self.assertIn('Café especial', home.text)
        self.assertIn(f'/portfolio/imagens/{filename}', home.text)
        self.assertEqual(home.text.count('class="carousel-item'), 6)
        self.assertIn('>Ver mais</strong>', home.text)
        full_gallery = self.client.get('/portfolio')
        self.assertEqual(full_gallery.status_code, 200)
        self.assertIn('Café especial', full_gallery.text)

    def test_users_menu_lists_registered_accounts_without_secrets(self):
        dashboard = self.client.get('/admin/')
        self.assertIn('href="/admin/usuarios"', dashboard.text)
        page = self.client.get('/admin/usuarios')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Admin Teste', page.text)
        self.assertIn('admin@example.test', page.text)
        self.assertIn('Hortolândia', page.text)
        self.assertIn('href="/admin/cadastro"', page.text)
        self.assertNotIn('password_hash', page.text)
        self.assertNotIn(self.password, page.text)
        visitor = self.app.test_client()
        self.assertEqual(visitor.get('/admin/usuarios').location, '/admin/login')

    def test_edit_user_validates_updates_and_revokes_changed_email_session(self):
        with self.database() as db:
            user_id = db.execute('SELECT id FROM users WHERE email=?', ('admin@example.test',)).fetchone()[0]
        path = f'/admin/usuarios/{user_id}/editar'
        self.assertEqual(self.app.test_client().get(path).location, '/admin/login')
        self.assertEqual(self.client.get(path).status_code, 200)
        data = dict(csrf_token=self.csrf(), first_name='Nome novo', last_name='Teste',
                    email='admin@example.test', city='Campinas')
        self.assertEqual(self.client.post(path, data={**data, 'email': 'invalido'}).status_code, 400)
        self.assertEqual(self.client.post(path, data={}).status_code, 400)
        self.assertEqual(self.client.post(path, data=data).location, '/admin/usuarios?updated=1')
        self.assertIn('Nome novo', self.client.get('/admin/usuarios').text)
        self.assertEqual(self.client.post(path, data={**data, 'email': 'novo@example.test'}).location, '/admin/login')
        self.assertEqual(self.client.get('/admin/usuarios').location, '/admin/login')
        with self.database() as db:
            self.assertEqual(db.execute('SELECT email FROM users WHERE id=?', (user_id,)).fetchone()[0], 'novo@example.test')

    def test_authenticated_admin_can_create_user_and_return_to_list(self):
        form = self.client.get('/admin/cadastro')
        self.assertEqual(form.status_code, 200)
        self.assertIn('Voltar para usuários', form.text)
        response = self.client.post('/admin/cadastro', data={
            'csrf_token': self.csrf(), 'first_name': 'Joana', 'last_name': 'Lima',
            'email': 'joana@example.test', 'email_confirmation': 'joana@example.test',
            'password': 'senha123', 'password_confirmation': 'senha123', 'city': 'Sumaré',
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, '/admin/usuarios?created=1')
        page = self.client.get(response.location)
        self.assertIn('Novo usuário criado com sucesso.', page.text)
        self.assertIn('Joana Lima', page.text)
        self.assertIn('2 usuários cadastrados', page.text)

    def test_portfolio_rejects_file_with_fake_image_extension(self):
        self.client.get('/admin/portfolio')
        response = self.client.post('/admin/portfolio/imagens', data={
            'csrf_token': self.csrf(), 'title': 'Arquivo falso',
            'image': (BytesIO(b'isto nao e uma imagem'), 'falsa.jpg'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 400)
        self.assertIn('JPEG, PNG ou WebP válida', response.text)

    def test_photo_edit_hide_replace_restore_and_delete(self):
        self.client.get('/admin/portfolio')
        self.client.post('/admin/portfolio/imagens', data={
            'csrf_token': self.csrf(), 'title': 'Original',
            'image': (BytesIO(b'\xff\xd8\xff\xe0test'), 'original.jpg'),
        })
        with self.database() as db:
            image_id, filename = db.execute('SELECT id, filename FROM portfolio_images').fetchone()
        edit_url = f'/admin/portfolio/{image_id}/editar'
        data = dict(csrf_token=self.csrf(), title='Título novo', description='Texto novo', hidden='1')
        self.assertEqual(self.client.post(edit_url, data=data).status_code, 303)
        for path in ['/', '/portfolio']:
            self.assertNotIn('Título novo', self.client.get(path).text)
        self.assertIn('Título novo', self.client.get('/admin/portfolio').text)
        self.assertEqual(self.client.get(f'/portfolio/imagens/{filename}').status_code, 404)
        with self.client.get(f'/admin/portfolio/imagens/{filename}') as response:
            self.assertEqual(response.status_code, 200)
        bad = self.client.post(edit_url, data={**data, 'image': (BytesIO(b'invalid'), 'bad.jpg')})
        self.assertEqual(bad.status_code, 400)
        self.assertTrue((Path(self.directory.name) / 'portfolio' / filename).exists())
        replaced = self.client.post(edit_url, data={**data, 'hidden': '', 'image': (BytesIO(b'\x89PNG\r\n\x1a\nreplacement'), 'new.png')})
        self.assertEqual(replaced.status_code, 303)
        with self.database() as db:
            new_filename = db.execute('SELECT filename FROM portfolio_images WHERE id=?', (image_id,)).fetchone()[0]
        self.assertNotEqual(filename, new_filename)
        self.assertFalse((Path(self.directory.name) / 'portfolio' / filename).exists())
        self.assertIn('Título novo', self.client.get('/').text)
        delete_url = f'/admin/portfolio/{image_id}/excluir'
        self.assertEqual(self.client.get(delete_url).status_code, 200)
        self.assertEqual(self.client.post(delete_url, data={}).status_code, 400)
        self.assertEqual(self.client.post(delete_url, data={'csrf_token': self.csrf()}).status_code, 400)
        self.assertEqual(self.client.get(edit_url).status_code, 200)
        self.assertEqual(self.client.post(delete_url, data={'csrf_token': self.csrf(), 'confirm_delete': '1'}).status_code, 303)
        self.assertEqual(self.client.get(edit_url).status_code, 404)
        self.assertFalse((Path(self.directory.name) / 'portfolio' / new_filename).exists())
        self.assertNotIn('Título novo', self.client.get('/').text)

    def test_admin_without_trailing_slash_redirects_to_panel(self):
        response = self.client.get('/admin')
        self.assertEqual(response.status_code, 200)

    def test_admin_redirects_to_login_without_session(self):
        visitor = self.app.test_client()
        response = visitor.get('/admin/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/admin/login')
        self.assertEqual(visitor.get('/admin/portfolio').location, '/admin/login')

    def test_login_has_only_email_and_password_visible_fields(self):
        visitor = self.app.test_client()
        page = visitor.get('/admin/login').text
        self.assertIn('type="email"', page)
        self.assertIn('type="password"', page)
        self.assertNotIn('href="/admin/portfolio"', page)
        self.assertIn('href="/admin/esqueci-senha"', page)
        stylesheet = visitor.get('/admin.css')
        self.assertEqual(stylesheet.status_code, 200)
        self.assertEqual(stylesheet.mimetype, 'text/css')

    def test_wrong_password_does_not_send_code_or_open_admin(self):
        visitor = self.app.test_client()
        visitor.get('/admin/login')
        sent_before = len(self.mailbox)
        response = visitor.post('/admin/login', data={
            'csrf_token': self.csrf(visitor), 'email': 'admin@example.test', 'password': 'senha-incorreta',
        })
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(self.mailbox), sent_before)
        self.assertEqual(visitor.get('/admin/').location, '/admin/login')

    def test_login_does_not_block_after_repeated_wrong_passwords(self):
        visitor = self.app.test_client()
        visitor.get('/admin/login')
        for _ in range(6):
            response = visitor.post('/admin/login', data={
                'csrf_token': self.csrf(visitor), 'email': 'admin@example.test', 'password': 'senha-incorreta',
            })
            self.assertEqual(response.status_code, 401)
            self.assertNotIn('Muitas tentativas', response.text)
        correct = visitor.post('/admin/login', data={
            'csrf_token': self.csrf(visitor), 'email': 'admin@example.test', 'password': self.password,
        })
        self.assertEqual(correct.status_code, 303)
        self.assertEqual(correct.location, '/admin/verificar')

    def test_gmail_authentication_failure_explains_app_password(self):
        visitor = self.app.test_client()
        visitor.get('/admin/login')
        self.app.config['SEND_CODE'] = lambda _email, _code: (_ for _ in ()).throw(
            smtplib.SMTPAuthenticationError(535, b'credentials rejected')
        )
        response = visitor.post('/admin/login', data={
            'csrf_token': self.csrf(visitor), 'email': 'admin@example.test', 'password': self.password,
        })
        self.assertEqual(response.status_code, 503)
        self.assertIn('senha de app do Google', response.text)
        self.assertNotIn('credentials rejected', response.text)

    def test_user_registration_validates_and_creates_login(self):
        visitor = self.client
        page = visitor.get('/admin/cadastro')
        self.assertEqual(page.status_code, 200)
        for field in ('first_name', 'last_name', 'email', 'email_confirmation', 'password', 'password_confirmation', 'city'):
            self.assertIn(f'name="{field}"', page.text)
        data = {
            'csrf_token': self.csrf(visitor), 'first_name': 'Marina', 'last_name': 'Silva',
            'email': 'marina@example.test', 'email_confirmation': 'marina@example.test',
            'password': 'senha123', 'password_confirmation': 'senha123',
            'city': 'Hortolândia',
        }
        created = visitor.post('/admin/cadastro', data=data)
        self.assertEqual(created.status_code, 303)
        self.assertEqual(created.location, '/admin/usuarios?created=1')
        with self.database() as db:
            user = db.execute('SELECT first_name, last_name, city, password_hash FROM users WHERE email = ?', ('marina@example.test',)).fetchone()
        self.assertEqual(user[:3], ('Marina', 'Silva', 'Hortolândia'))
        self.assertNotEqual(user[3], data['password'])
        visitor = self.app.test_client()
        visitor.get('/admin/login')
        login = visitor.post('/admin/login', data={
            'csrf_token': self.csrf(visitor), 'email': data['email'], 'password': data['password'],
        })
        self.assertEqual(login.status_code, 303)
        self.assertEqual(self.mailbox[-1][0], data['email'])
        self.assertEqual(visitor.get('/admin/').status_code, 302)
        verified = visitor.post('/admin/verificar', data={
            'csrf_token': self.csrf(visitor), 'code': self.mailbox[-1][1],
        })
        self.assertEqual(verified.status_code, 303)
        self.assertEqual(visitor.get('/admin/').status_code, 200)

    def test_registration_rejects_mismatches_and_duplicate_email(self):
        visitor = self.client
        visitor.get('/admin/cadastro')
        base = {
            'csrf_token': self.csrf(visitor), 'first_name': 'Ana', 'last_name': 'Souza',
            'email': 'ana@example.test', 'email_confirmation': 'outra@example.test',
            'password': 'uma-senha-segura-123', 'password_confirmation': 'diferente-segura-123',
            'city': 'Campinas',
        }
        self.assertEqual(visitor.post('/admin/cadastro', data=base).status_code, 400)
        valid = {**base, 'email_confirmation': base['email'], 'password_confirmation': base['password']}
        self.assertEqual(visitor.post('/admin/cadastro', data=valid).status_code, 303)
        visitor.get('/admin/cadastro')
        valid['csrf_token'] = self.csrf(visitor)
        self.assertEqual(visitor.post('/admin/cadastro', data=valid).status_code, 409)

    def test_registration_requires_completed_login_and_csrf(self):
        visitor = self.app.test_client()
        login = visitor.get('/admin/login')
        self.assertNotIn('href="/admin/cadastro"', login.text)
        data = dict(csrf_token=self.csrf(visitor), first_name='Intruso', last_name='Teste',
                    email='intruso@example.test', email_confirmation='intruso@example.test',
                    password='senha123', password_confirmation='senha123', city='Teste')
        for method in (visitor.get, visitor.post):
            response = method('/admin/cadastro', **({'data': data} if method == visitor.post else {}))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, '/admin/login')
        visitor.post('/admin/login', data={'csrf_token': self.csrf(visitor),
                     'email': 'admin@example.test', 'password': self.password})
        data['csrf_token'] = self.csrf(visitor)
        self.assertEqual(visitor.post('/admin/cadastro', data=data).status_code, 302)
        self.assertEqual(self.client.post('/admin/cadastro', data={**data, 'csrf_token': 'invalid'}).status_code, 400)
        with self.database() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 1)

    def test_production_enforces_https_hosts_and_secure_cookies(self):
        production = create_app({'TESTING': True, 'SECRET_KEY': 'test-only',
                                 'DATA_DIR': self.directory.name, 'PRODUCTION': True,
                                 'TRUSTED_HOSTS': ['foto.example.test']})
        client = production.test_client()
        self.assertEqual(client.get('/admin/login', base_url='http://foto.example.test').status_code, 400)
        self.assertEqual(client.get('/admin/login', base_url='http://foto.example.test',
                                   headers={'X-Forwarded-Proto': 'https'}).status_code, 400)
        self.assertEqual(client.get('/admin/login', base_url='https://evil.example.test').status_code, 400)
        response = client.get('/admin/login', base_url='https://foto.example.test')
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['Set-Cookie']
        for flag in ('__Host-fg_admin=', 'Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/'):
            self.assertIn(flag, cookie)
        self.assertNotIn('Domain=', cookie)
        self.assertEqual(response.headers['Strict-Transport-Security'], 'max-age=31536000')
        with patch.dict('os.environ', {'FG_TRUSTED_HOSTS': ''}):
            with self.assertRaises(ValueError):
                create_app({'PRODUCTION': True, 'DATA_DIR': self.directory.name})

    def test_reset_code_cannot_be_used_as_login_code(self):
        visitor = self.app.test_client()
        visitor.get('/admin/esqueci-senha')
        visitor.post('/admin/esqueci-senha', data={'csrf_token': self.csrf(visitor), 'email': 'admin@example.test'})
        with visitor.session_transaction() as session:
            session['pending'] = session['pending_reset']
        response = visitor.post('/admin/verificar', data={'csrf_token': self.csrf(visitor), 'code': self.mailbox[-1][1]})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(visitor.get('/admin/').status_code, 302)

    def test_forgot_password_resets_password_and_allows_login(self):
        visitor = self.app.test_client()
        page = visitor.get('/admin/esqueci-senha')
        self.assertEqual(page.status_code, 200)
        requested = visitor.post('/admin/esqueci-senha', data={
            'csrf_token': self.csrf(visitor), 'email': 'admin@example.test',
        })
        self.assertEqual(requested.status_code, 303)
        self.assertEqual(requested.location, '/admin/redefinir-senha')
        reset_code = self.mailbox[-1][1]
        reset = visitor.post('/admin/redefinir-senha', data={
            'csrf_token': self.csrf(visitor), 'code': reset_code,
            'password': 'nova1234', 'password_confirmation': 'nova1234',
        })
        self.assertEqual(reset.status_code, 303)
        self.assertEqual(reset.location, '/admin/login?reset=1')
        visitor.get('/admin/login')
        old_password = visitor.post('/admin/login', data={
            'csrf_token': self.csrf(visitor), 'email': 'admin@example.test', 'password': self.password,
        })
        self.assertEqual(old_password.status_code, 401)
        new_password = visitor.post('/admin/login', data={
            'csrf_token': self.csrf(visitor), 'email': 'admin@example.test', 'password': 'nova1234',
        })
        self.assertEqual(new_password.status_code, 303)

    def test_forgot_password_rejects_wrong_code_and_short_password(self):
        visitor = self.app.test_client()
        visitor.get('/admin/esqueci-senha')
        visitor.post('/admin/esqueci-senha', data={
            'csrf_token': self.csrf(visitor), 'email': 'admin@example.test',
        })
        wrong_code = '000000' if self.mailbox[-1][1] != '000000' else '111111'
        wrong = visitor.post('/admin/redefinir-senha', data={
            'csrf_token': self.csrf(visitor), 'code': wrong_code,
            'password': 'nova1234', 'password_confirmation': 'nova1234',
        })
        self.assertEqual(wrong.status_code, 401)
        short = visitor.post('/admin/redefinir-senha', data={
            'csrf_token': self.csrf(visitor), 'code': self.mailbox[-1][1],
            'password': 'curta', 'password_confirmation': 'curta',
        })
        self.assertEqual(short.status_code, 400)

    def test_logout_revokes_session(self):
        response = self.client.post('/admin/sair', data={'csrf_token': self.csrf()})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, '/admin/login')
        self.assertEqual(self.client.get('/admin/').location, '/admin/login')

    def test_dashboard_shows_protected_access_and_logout(self):
        page = self.client.get('/admin/').text
        self.assertIn('Acesso protegido', page)
        self.assertIn('action="/admin/sair"', page)

    def test_private_files_remain_unavailable(self):
        for path in ['/.git/config', '/server.py', '/admin.sqlite3', '/smtp.json', '/.env', '/templates/dashboard.html', '/../.fotografia-admin/smtp.json']:
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_security_headers_remain_enabled(self):
        response = self.client.get('/admin/')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("form-action 'self'", response.headers['Content-Security-Policy'])

    def test_calendar_lists_visits_by_month(self):
        self.client.get('/admin/?month=2026-10')
        response = self.client.post('/admin/visitas', data={
            'csrf_token': self.csrf(), 'client': 'Café da praça',
            'visit_date': '2026-10-17', 'visit_time': '10:30', 'visit_type': 'ensaio',
            'equipment': 'Canon R10 e flash Godox', 'notes': 'Levar fundo claro',
        })
        self.assertEqual(response.status_code, 302)
        page = self.client.get('/admin/?month=2026-10')
        self.assertIn('Café da praça', page.text)
        self.assertIn('10:30', page.text)
        self.assertIn('Café da praça - 10:30', page.text)
        self.assertIn('visit-preview', page.text)
        self.assertIn('Levar fundo claro', page.text)
        self.assertIn('Canon R10 e flash Godox', page.text)
        with self.database() as db:
            visit_id = db.execute('SELECT id FROM visits').fetchone()[0]
        detail = self.client.get(f'/admin/visitas/{visit_id}')
        self.assertIn('Levar fundo claro', detail.text)
        self.assertIn('Canon R10 e flash Godox', detail.text)
        self.assertNotIn('10:30', self.client.get('/admin/?month=2026-11').text)

    def test_calendar_rejects_invalid_visit(self):
        self.client.get('/admin/')
        response = self.client.post('/admin/visitas', data={
            'csrf_token': self.csrf(), 'client': 'Café da praça',
            'visit_date': 'data inválida', 'visit_time': '10:30',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('data e um horário válidos', response.text)

    def test_event_author_is_authenticated_user_and_survives_edits(self):
        for kind in ('reuniao', 'ensaio'):
            payload = dict(csrf_token=self.csrf(), client='Autoria ' + kind,
                           visit_date='2027-10-17', visit_time='10:30', visit_type=kind,
                           equipment='Canon R10', created_by_name='Nome forjado', created_by_id='999')
            self.assertEqual(self.client.post('/admin/visitas', data=payload).status_code, 302)
            with self.database() as db:
                visit_id, author_id, author_name = db.execute('SELECT id, created_by_id, created_by_name FROM visits ORDER BY id DESC LIMIT 1').fetchone()
                expected_id = db.execute("SELECT id FROM users WHERE email='admin@example.test'").fetchone()[0]
            self.assertEqual(author_id, expected_id)
            self.assertEqual(author_name, 'Admin Teste')
            self.assertIn('Cadastrado por: Admin Teste', self.client.get(f'/admin/visitas/{visit_id}').text)
            self.assertIn('Cadastrado por: Admin Teste', self.client.get('/admin/?month=2027-10').text)
            self.assertEqual(self.client.post(f'/admin/visitas/{visit_id}/editar', data=payload).status_code, 302)
            with self.database() as db:
                self.assertEqual(db.execute('SELECT created_by_name FROM visits WHERE id=?', (visit_id,)).fetchone()[0], 'Admin Teste')

    def test_legacy_event_does_not_invent_author(self):
        with self.database() as db:
            db.execute("INSERT INTO visits (visit_date, visit_time, client, created_at) VALUES ('2027-10-17', '10:30', 'Antigo', '2026-09-01')")
            db.commit()
            visit_id = db.execute('SELECT id FROM visits').fetchone()[0]
        self.assertIn('Não registrado (evento anterior a este recurso)', self.client.get(f'/admin/visitas/{visit_id}').text)

    def test_calendar_requires_equipment_for_ensaios_and_five_minute_steps(self):
        self.client.get('/admin/')
        missing_equipment = self.client.post('/admin/visitas', data={
            'csrf_token': self.csrf(), 'client': 'Café da praça',
            'visit_date': '2026-10-17', 'visit_time': '10:30', 'visit_type': 'ensaio',
        })
        self.assertEqual(missing_equipment.status_code, 400)
        self.assertIn('equipamentos necessários', missing_equipment.text)
        self.assertIn('id="new-visit-dialog" checked', missing_equipment.text)
        self.assertIn('field-invalid', missing_equipment.text)
        self.assertIn('aria-invalid="true"', missing_equipment.text)
        invalid_minutes = self.client.post('/admin/visitas', data={
            'csrf_token': self.csrf(), 'client': 'Café da praça',
            'visit_date': '2026-10-17', 'visit_time': '10:07', 'visit_type': 'reuniao',
        })
        self.assertEqual(invalid_minutes.status_code, 400)

    def test_time_controls_offer_only_five_minute_options(self):
        page = self.client.get('/admin/').text
        self.assertIn('name="visit_minute"', page)
        self.assertIn('value="00"', page)
        self.assertIn('value="05"', page)
        self.assertIn('value="55"', page)
        self.assertNotIn('<option value="07">07</option>', page)

    def test_selecting_calendar_day_opens_form_with_selected_date(self):
        page = self.client.get('/admin/?month=2027-02')
        self.assertIn('new_date=2027-02-28', page.text)
        self.assertNotIn('new_date=2027-02-29', page.text)
        selected = self.client.get('/admin/?month=2026-09&new_date=2027-02-28')
        self.assertEqual(selected.status_code, 200)
        self.assertIn('fevereiro de 2027', selected.text)
        self.assertIn('id="new-visit-dialog" checked', selected.text)
        self.assertIn('required value="2027-02-28"', selected.text)
        self.assertEqual(self.client.get('/admin/?new_date=2027-02-30').status_code, 400)

    def test_event_can_be_opened_edited_and_deleted(self):
        self.client.get('/admin/')
        created = self.client.post('/admin/visitas', data={
            'csrf_token': self.csrf(), 'client': 'Café da praça',
            'visit_date': '2026-10-17', 'visit_time': '10:30', 'visit_type': 'reuniao',
        })
        self.assertEqual(created.status_code, 302)
        with self.database() as db:
            visit_id = db.execute('SELECT id FROM visits').fetchone()[0]
        detail = self.client.get(f'/admin/visitas/{visit_id}')
        self.assertEqual(detail.status_code, 200)
        self.assertIn('Salvar alterações', detail.text)
        edited = self.client.post(f'/admin/visitas/{visit_id}/editar', data={
            'csrf_token': self.csrf(), 'client': 'Café renovado', 'visit_date': '2026-10-18',
            'visit_hour': '11', 'visit_minute': '05', 'visit_type': 'ensaio',
            'equipment': 'Canon R10', 'notes': 'Confirmar endereço',
        })
        self.assertEqual(edited.status_code, 302)
        self.assertIn('Café renovado', self.client.get(f'/admin/visitas/{visit_id}').text)
        deleted = self.client.post(f'/admin/visitas/{visit_id}/excluir', data={'csrf_token': self.csrf()})
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(self.client.get(f'/admin/visitas/{visit_id}').status_code, 404)


if __name__ == '__main__':
    unittest.main()
