"""Testes do painel local, sem autenticação ou envio de e-mail."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from server import create_app


class AdminPanelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app({
            'TESTING': True,
            'SECRET_KEY': 'isolated-test-key',
            'DATA_DIR': self.directory.name,
        })
        self.client = self.app.test_client()
        with closing(sqlite3.connect(Path(self.directory.name) / 'admin.sqlite3')) as db, db:
            db.execute('INSERT INTO admin VALUES (1, ?, ?)', ('admin@example.test', 'hash-unused'))

    def csrf(self):
        with self.client.session_transaction() as session:
            return session['csrf']

    def database(self):
        return closing(sqlite3.connect(Path(self.directory.name) / 'admin.sqlite3'))

    def test_admin_opens_without_login(self):
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'admin@example.test', response.data)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_admin_without_trailing_slash_redirects_to_panel(self):
        response = self.client.get('/admin')
        self.assertEqual(response.status_code, 200)

    def test_authentication_pages_are_removed(self):
        for path in ['/admin/login', '/admin/verificar', '/admin/reenviar']:
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_dashboard_does_not_show_authentication_controls(self):
        page = self.client.get('/admin/').text
        self.assertNotIn('Sair da conta', page)
        self.assertNotIn('login', page.lower())
        self.assertNotIn('senha', page.lower())

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
        self.assertIn('Levar fundo claro', page.text)
        self.assertIn('Canon R10 e flash Godox', page.text)
        self.assertNotIn('10:30', self.client.get('/admin/?month=2026-11').text)

    def test_calendar_rejects_invalid_visit(self):
        self.client.get('/admin/')
        response = self.client.post('/admin/visitas', data={
            'csrf_token': self.csrf(), 'client': 'Café da praça',
            'visit_date': 'data inválida', 'visit_time': '10:30',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('data e um horário válidos', response.text)

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
