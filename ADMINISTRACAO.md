# Administração local

Branch: `feature/painel-sem-autenticacao`. O painel é uma área local de edição, sem tela de autenticação. Não há contas ou senhas padrão.

## Iniciar

Na pasta `site/` deste projeto:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py serve --port 8081
```

Se o ambiente já estiver instalado, basta o último comando. Abra **http://127.0.0.1:8081/admin/** para acessar o painel. A versão pública desta branch também está em http://127.0.0.1:8081/. O servidor está limitado a este computador. A porta 8081 permite preservar a prévia anterior em 8080 durante a revisão.

O servidor estático `python3 -m http.server` não executa autenticação. Para esta branch, use `server.py`. Não sirva a pasta do repositório inteiro com um servidor estático; o servidor novo entrega somente os arquivos públicos permitidos.

## Fluxo

`/admin/` abre diretamente o painel local. As páginas `/admin/login`, `/admin/verificar` e `/admin/reenviar` foram removidas. O acesso deve permanecer restrito ao computador local; este painel não deve ser exposto à internet sem uma camada de autenticação.

## Dados locais

O banco local continua em **`.fotografia-admin/`, na pasta acima de `site/`**, fora do repositório e das rotas públicas. Não copie essa pasta para o GitHub.

## Agenda de visitas

No painel, a seção **Agenda de visitas** mostra o mês selecionado e permite avançar ou voltar entre meses. O botão **Nova visita** abre um pop-up para escolher entre reunião e ensaio, registrar estabelecimento, data e horário em intervalos de cinco minutos. Em ensaios, o campo de equipamentos é obrigatório. Clique em um evento para abrir sua ficha, editar os dados ou excluí-lo. Os compromissos ficam na tabela `visits` do banco local e são consultados apenas pelo servidor local.

## Verificação

```sh
.venv/bin/python -m unittest -v test_auth
```

Os testes usam banco temporário e verificam acesso direto ao painel, remoção das rotas de autenticação, cabeçalhos de segurança e bloqueio de arquivos privados. Nenhuma mensagem é enviada pelos testes.

## Hospedagem futura

Esta execução é local, com Flask sem modo debug. Para hospedar será preciso escolher servidor WSGI, armazenamento persistente, HTTPS, cookies Secure, domínio permitido e configuração de e-mail de produção. As definições atuais de host são restritas a localhost/127.0.0.1. Não expor este servidor local à internet.

As decisões de cookies, CSRF e cabeçalhos seguem a [documentação de segurança do Flask](https://flask.palletsprojects.com/en/stable/web-security/).
