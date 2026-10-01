#!/bin/bash
# Executar na VPS somente após conferir A/AAAA do domínio e www.
set -euo pipefail
for domain in cliquenoprato.com.br www.cliquenoprato.com.br; do
    resolved=$(dig @1.1.1.1 +short "$domain" A | tail -1)
    if [ "$resolved" != "143.95.168.93" ]; then
        echo "DNS ainda não aponta para a VPS: $domain"
        exit 1
    fi
    if [ -n "$(dig @1.1.1.1 +short "$domain" AAAA | grep ':')" ]; then
        echo "Revisar IPv6 de $domain antes de emitir certificado."
        exit 1
    fi
done
certbot certonly --webroot -w /var/www/letsencrypt \
    -d cliquenoprato.com.br -d www.cliquenoprato.com.br \
    --email figasphoto@gmail.com --agree-tos --non-interactive
cat > /etc/nginx/sites-available/clique-no-prato <<'NGINX'
# Não registrar query strings: links de redefinição contêm tokens.
log_format clique_safe '$remote_addr [$time_local] "$request_method $uri $server_protocol" $status $body_bytes_sent';
server {
    listen 80 default_server;
    server_name _;
    server_tokens off;
    access_log /var/log/nginx/clique-access.log clique_safe;
    return 444;
}
server {
    listen 80;
    server_name cliquenoprato.com.br www.cliquenoprato.com.br;
    server_tokens off;
    access_log /var/log/nginx/clique-access.log clique_safe;
    location /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / { return 301 https://cliquenoprato.com.br$request_uri; }
}
server {
    listen 443 ssl;
    server_name cliquenoprato.com.br www.cliquenoprato.com.br;
    ssl_certificate /etc/letsencrypt/live/cliquenoprato.com.br/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/cliquenoprato.com.br/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    server_tokens off;
    client_max_body_size 12m;
    access_log /var/log/nginx/clique-access.log clique_safe;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_hide_header Server;
        proxy_read_timeout 65s;
    }
}
NGINX
nginx -t
systemctl reload nginx
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\nnginx -t && systemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
systemctl enable --now certbot.timer
