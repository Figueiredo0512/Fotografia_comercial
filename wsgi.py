"""Entrada de produção: exige hosts configurados e transporte HTTPS."""
from server import create_app

app = create_app({'PRODUCTION': True})
