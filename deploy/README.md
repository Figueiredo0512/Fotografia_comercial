# Hospedagem do Clique no Prato

Site: https://cliquenoprato.com.br/
Painel: https://www.cliquenoprato.com.br/admin

Em 01/10/2026, verificados por HTTPS: site com resposta 200 e painel anônimo com redirecionamento 302 para /admin/login. Certificado emitido em 30/09/2026 pelo script executado pela pessoa usuária. Ambos os domínios atendem HTTPS; o redirecionamento canônico exclusivo para www ainda não foi aplicado.

## Ambiente

- VPS HostGator Ubuntu 22.04, IP 143.95.168.93, SSH na porta 22022.
- Código em /opt/clique-no-prato/site, executado pelo usuário de serviço clique.
- Python em .venv, dependências de requirements.txt e Gunicorn 26.2.0.
- Gunicorn em 127.0.0.1:8000, atrás de Nginx, com serviço systemd clique-no-prato.
- Dados privados em /opt/clique-no-prato/.fotografia-admin, fora do repositório e da área pública.
- UFW libera SSH 22022, HTTP 80 e HTTPS 443.

## Scripts

`configure-server.sh` registra a configuração inicial de systemd, Nginx provisório e firewall. Exige código, ambiente Python e usuário clique já preparados. **Não executar novamente em produção: ele substitui o Nginx por uma configuração provisória que responde 503.**

`ativar-https.sh` confere DNS, emite o certificado, aplica o proxy HTTPS e configura o timer de renovação com recarga do Nginx. Executar como root na VPS, após o preparo inicial. O script altera a configuração do Nginx; preservar uma cópia da configuração vigente antes de reutilizá-lo.

Não são instaladores completos nem scripts de atualização. Dependências de sistema necessárias: python3-venv, python3-pip, nginx, certbot, python3-certbot-nginx, ufw e dnsutils.

## Operação e atualização

```sh
systemctl status clique-no-prato nginx
nginx -t
systemctl restart clique-no-prato
systemctl status certbot.timer
```

Antes de atualizar, fazer backup consistente do SQLite e das fotos. Trocar apenas o código aprovado, instalar as dependências e reiniciar o serviço. Nunca substituir o banco da VPS pela cópia local: os dados passaram a ser independentes após a migração.

Senhas, configuração SMTP, certificados privados, chave de sessão, banco e uploads não devem entrar no Git. Não enviar e-mails nos testes automatizados. A instalação original passou nos 38 testes de test_auth; recebimento real dos códigos deve ser validado pelo administrador. Backup externo e teste de restauração permanecem pendentes.
