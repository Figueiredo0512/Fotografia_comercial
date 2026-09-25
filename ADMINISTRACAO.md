# Administração local

Branch: `feature/area-administrativa`. Primeiro incremento: acesso por senha, confirmação por e-mail, painel protegido e saída. A edição de textos e contatos foi escolhida como próximo incremento, após validar o acesso. Não há contas ou senhas padrão.

## Iniciar

Na pasta `site/` deste projeto:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py serve --port 8081
```

Se o ambiente já estiver instalado, basta o último comando. Abra **http://127.0.0.1:8081/admin/login**. A versão pública desta branch também está em http://127.0.0.1:8081/. O servidor está limitado a este computador. A porta 8081 permite preservar a prévia anterior em 8080 durante a revisão.

O servidor estático `python3 -m http.server` não executa autenticação. Para esta branch, use `server.py`. Não sirva a pasta do repositório inteiro com um servidor estático; o servidor novo entrega somente os arquivos públicos permitidos.

## Cadastrar o administrador

E-mail confirmado pela pessoa usuária: **figasphoto@gmail.com**.

No Terminal, execute:

```sh
.venv/bin/python server.py init-admin --email figasphoto@gmail.com
```

Digite e repita uma senha própria do painel, com pelo menos 12 caracteres. Ela não aparece no Terminal. Não use a senha da caixa de e-mail e não cole senhas na conversa. Só o hash scrypt é armazenado. O comando não substitui uma conta existente.

## Configurar o envio de códigos

```sh
.venv/bin/python server.py configure-email
```

O assistente pergunta servidor, porta, usuário, remetente e credencial de envio. A credencial é digitada de forma oculta. Esse comando apenas salva a configuração; o código é enviado quando você entra com e-mail e senha corretos.

Se optar pelo Gmail, use:

| Campo | Valor |
|---|---|
| Servidor | `smtp.gmail.com` |
| Porta | `587` (STARTTLS) |
| Usuário | `figasphoto@gmail.com` |
| Remetente | `figasphoto@gmail.com` |
| Credencial | Senha de app criada na conta Google, se esse recurso estiver disponível |

A conta Google precisa ter verificação em duas etapas para usar senha de app. Algumas contas não disponibilizam essa opção; nesse caso, configure outro serviço SMTP compatível. Não é necessário fornecer a senha normal do Gmail. Consulte a [orientação oficial do Google](https://support.google.com/accounts/answer/185833?hl=pt-BR).

Ao colar a senha de app do Gmail, os espaços de separação são aceitos e removidos automaticamente pelo servidor. A senha continua armazenada somente no arquivo privado de configuração.

Depois de configurar, entre no navegador, confira a mensagem na caixa de entrada/spam e digite o código recebido. A configuração SMTP é lida no próximo acesso, sem exigir reinício. O envio real e a chegada à caixa de entrada precisam ser validados com a sua configuração. Em caso de falha de envio, o painel continua fechado e a tela informa o erro; não há código exibido em logs nem atalho de acesso.

## Fluxo

1. `/admin/login`: somente campos de e-mail e senha, além do botão Entrar.
2. `/admin/verificar`: código de seis dígitos entregue ao administrador cadastrado, válido por até dez minutos.
3. `/admin/`: painel liberado somente depois das duas etapas; sessão de até uma hora.
4. Sair revoga a sessão no servidor. Reusar o cookie anterior não reabre o painel.

O reenvio exige intervalo de 60 segundos e tem limite de três envios por acesso. O código antigo é substituído; o reenvio não reinicia o orçamento de cinco tentativas nem prolonga o prazo total. Muitas tentativas de senha também são limitadas por conta e endereço de origem, com contagem persistida no banco.

## Dados locais

Banco, chave de sessão e configuração SMTP ficam em **`.fotografia-admin/`, na pasta acima de `site/`**, fora do repositório e das rotas públicas. O diretório é restrito ao usuário do computador (0700) e os arquivos de credenciais recebem 0600. A credencial SMTP fica em arquivo local restrito; não há promessa de criptografia em repouso. Não copie essa pasta para o GitHub.

Para trocar a senha do painel localmente:

```sh
.venv/bin/python server.py reset-password
```

Isso também encerra sessões e códigos anteriores. Não existe recuperação pública de senha nesta primeira versão.

## Verificação

```sh
.venv/bin/python -m unittest -v test_auth
```

Os testes usam banco temporário e transporte de e-mail simulado. Cobrem duas etapas obrigatórias, código errado/expirado/reutilizado, reenvio, limites de tentativa, falha de SMTP, CSRF, sessão expirada, logout e bloqueio de arquivos privados. Nenhuma mensagem real é enviada pelos testes.

## Hospedagem futura

Esta execução é local, com Flask sem modo debug. Para hospedar será preciso escolher servidor WSGI, armazenamento persistente, HTTPS, cookies Secure, domínio permitido e configuração de e-mail de produção. As definições atuais de host são restritas a localhost/127.0.0.1. Não expor este servidor local à internet.

As decisões de cookies, CSRF e cabeçalhos seguem a [documentação de segurança do Flask](https://flask.palletsprojects.com/en/stable/web-security/).
