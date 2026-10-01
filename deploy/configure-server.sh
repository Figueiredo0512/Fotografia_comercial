#!/bin/bash
set -euo pipefail
cat > /etc/systemd/system/clique-no-prato.service <<'SERVICE'
[Unit]
Description=Clique no Prato - Flask
After=network.target
[Service]
User=clique
Group=clique
WorkingDirectory=/opt/clique-no-prato/site
Environment=FG_TRUSTED_HOSTS=cliquenoprato.com.br,www.cliquenoprato.com.br
Environment=FG_ENV=production
ExecStart=/opt/clique-no-prato/site/.venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 2 --timeout 60 --forwarded-allow-ips=127.0.0.1 wsgi:app
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/clique-no-prato/.fotografia-admin
[Install]
WantedBy=multi-user.target
SERVICE
mkdir -p /var/www/letsencrypt
cat > /etc/nginx/sites-available/clique-no-prato <<'NGINX'
server {
    listen 80;
    server_name cliquenoprato.com.br www.cliquenoprato.com.br;
    server_tokens off;
    location /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / { return 503; }
}
NGINX
ln -sfn /etc/nginx/sites-available/clique-no-prato /etc/nginx/sites-enabled/clique-no-prato
if [ -L /etc/nginx/sites-enabled/default ]; then unlink /etc/nginx/sites-enabled/default; fi
nginx -t
systemctl daemon-reload
systemctl enable --now clique-no-prato
systemctl reload nginx
ufw allow 22022/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl is-active clique-no-prato nginx
