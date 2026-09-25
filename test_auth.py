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


if __name__ == '__main__':
    unittest.main()
