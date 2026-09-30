# Administração local

O painel exige e-mail, senha e um código enviado ao e-mail do administrador. Não há contas ou senhas padrão.

## Iniciar

Na pasta `site/` deste projeto:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py serve --port 8081
```

Se o ambiente já estiver instalado, basta o último comando. Abra **http://127.0.0.1:8081/admin/login**. A versão pública desta branch também está em http://127.0.0.1:8081/. O servidor está limitado a este computador.

O servidor estático `python3 -m http.server` não executa autenticação. Para esta branch, use `server.py`. Não sirva a pasta do repositório inteiro com um servidor estático; o servidor novo entrega somente os arquivos públicos permitidos.

## Configuração do acesso

O administrador já foi cadastrado anteriormente. Para trocar a senha pelo Terminal, execute `.venv/bin/python server.py reset-password` e informe uma senha própria do painel com pelo menos 8 caracteres. A senha é armazenada somente como hash.

Para configurar ou atualizar o envio do código, execute `.venv/bin/python server.py configure-email`. No Gmail, use `smtp.gmail.com`, porta `587`, o e-mail do administrador como usuário e remetente, e uma senha de app do Google. A senha normal do Gmail não funciona nesse fluxo. Credenciais são digitadas apenas no Terminal e não devem ser enviadas pela conversa.

O fluxo é: `/admin/login` recebe e-mail e senha; `/admin/verificar` recebe o código de seis dígitos; `/admin/` abre agenda e portfólio após as duas etapas. Somente um administrador já autenticado pode acessar `/admin/cadastro`, pelo botão **Novo usuário**. O código expira em dez minutos e a sessão em uma hora. O botão **Sair** encerra a sessão.

Não há bloqueio por quantidade de tentativas de e-mail e senha. O código de confirmação continua limitado a cinco tentativas por solicitação e expira em dez minutos.

O cadastro solicita nome, sobrenome, e-mail com confirmação, senha com confirmação e cidade. A senha precisa ter pelo menos 8 caracteres e fica armazenada somente como hash. O e-mail não pode ser repetido. Não há cadastro público: GET e POST exigem sessão administrativa validada por código, e POST também exige CSRF. Todas as contas são administrativas, sem níveis de privilégio. O primeiro administrador de uma instalação vazia deve ser criado no Terminal com `.venv/bin/python server.py init-admin --email SEU_EMAIL`, digitando a senha somente no prompt. Contas existentes não são removidas automaticamente; revise a lista de usuários antes de publicar.

O botão **Esqueci minha senha** abre `/admin/esqueci-senha`. O usuário informa o e-mail, recebe um código válido por dez minutos e define uma nova senha em `/admin/redefinir-senha`. A troca encerra as sessões anteriores dessa conta. O envio depende da mesma configuração SMTP usada pelo código de login e aceita até três solicitações por conta em 15 minutos.

## Dados locais

Banco, fotos, chave de sessão e configuração SMTP ficam em **`.fotografia-admin/`, na pasta acima de `site/`**, fora do repositório e das rotas públicas. Não copie essa pasta para o GitHub.

## Agenda de visitas

No painel, a seção **Agenda de visitas** mostra o mês selecionado e permite avançar ou voltar entre meses. O botão **Nova visita** abre um pop-up para escolher entre reunião e ensaio, registrar estabelecimento, data e horário em intervalos de cinco minutos. Em ensaios, o campo de equipamentos é obrigatório. Clique em um evento para abrir sua ficha, editar os dados ou excluí-lo. Os compromissos ficam na tabela `visits` do banco local e são consultados apenas pelo servidor local.

## Portfólio local

No envio e em **Editar foto**, o campo **Onde exibir a foto?** permite escolher **Portfólio** (carrossel e galeria) ou **01 / O primeiro olhar** (destaque da página inicial). As fotos anteriores permanecem no portfólio. O destaque aceita uma foto visível por vez: ao selecionar outra, a anterior é escondida e permanece na biblioteca. Para restaurá-la, edite e desmarque **Esconder foto**. Sem destaque visível, a página volta ao espaço reservado. A imagem de destaque preenche o quadro com recorte central; confira o enquadramento no celular. Os cards indicam destino e visibilidade.

Use **Editar foto** na biblioteca para alterar título, descrição ou substituir a imagem. **Esconder foto** retira a imagem da home, da galeria e do endereço público do arquivo, mantendo-a no painel. Desmarque para exibir novamente. **Excluir foto** abre uma confirmação e remove o cadastro e o arquivo; substituir a imagem também remove o arquivo anterior.

O menu superior oferece acesso à página **Portfólio**. Nela é possível enviar fotografias JPEG, PNG ou WebP de até 12 MB, com título e descrição. Os arquivos ficam em `.fotografia-admin/portfolio/` e os dados de organização ficam na tabela `portfolio_images` do banco local. Essa pasta não deve ser enviada ao GitHub.

O item **Usuários** abre `/admin/usuarios` e lista nome, e-mail, cidade e data de cadastro das contas com acesso ao painel. O botão **Novo usuário** abre o formulário de cadastro e, ao salvar, retorna à lista sem desconectar o administrador atual. Senhas, hashes, códigos e credenciais SMTP não são exibidos.

As cinco fotografias mais recentes aparecem automaticamente no carrossel da página inicial. O sexto card, **Ver mais**, abre `/portfolio`, onde todas as imagens cadastradas são apresentadas. Enquanto houver menos de cinco fotos, os lugares restantes continuam marcados como espaços reservados.

## Verificação

```sh
.venv/bin/python -m unittest -v test_auth
```

Os testes usam banco temporário e transporte de e-mail simulado. Verificam cadastro, senha mínima, recuperação de senha, login em duas etapas, proteção das rotas administrativas, calendário, portfólio, cabeçalhos de segurança e bloqueio de arquivos privados. Nenhuma mensagem real é enviada pelos testes.

## Hospedagem futura

Esta execução é local, com Flask sem modo debug e limitada a localhost/127.0.0.1. O servidor local responde `Server: Fotografia`, sem divulgar versões de Python/Werkzeug. Isso reduz informação exposta, mas não substitui atualizações. Cookies locais continuam sem `Secure` para permitir a prévia HTTP; esse modo não deve ser exposto à internet.

A entrada `wsgi:app` habilita obrigatoriamente o modo de produção. Configure `FG_TRUSTED_HOSTS` com os domínios exatos separados por vírgulas, sem esquema ou caminho. A aplicação recusa inicializar sem essa configuração. Em produção, o cookie usa `Secure`, `HttpOnly`, `SameSite=Strict` e prefixo `__Host-`, e as respostas HTTPS incluem HSTS. Requisições HTTP são recusadas antes do processamento dos formulários. `FG_ENV=production` também ativa essas regras; o comando `serve` recusa funcionar nesse modo.

Na VPS, após configurar domínio, certificado TLS e instalar Gunicorn, a execução será semelhante a:

```sh
FG_TRUSTED_HOSTS=seu-dominio.com.br .venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 2 --forwarded-allow-ips=127.0.0.1 wsgi:app
```

O domínio acima é um exemplo, não uma configuração já aplicada. O proxy Nginx deverá terminar HTTPS, redirecionar HTTP para o domínio HTTPS fixo e encaminhar apenas para `127.0.0.1:8000`. No bloco HTTPS, usar `proxy_set_header Host $host`, `proxy_set_header X-Forwarded-Proto $scheme` e `proxy_hide_header Server`; definir `server_tokens off` para não divulgar a versão do Nginx. O Gunicorn reconhece HTTPS somente de proxies autorizados pelo endereço de origem. Não usar `--forwarded-allow-ips='*'`, nem expor a porta 8000 ao público. A aplicação, por si só, não confia em um cabeçalho `X-Forwarded-Proto` enviado pelo visitante.

Certificado, proxy, serviço de inicialização automática, backups e envio real de e-mail ainda precisam ser configurados e verificados na hospedagem escolhida. Os testes locais simulam HTTPS; não confirmam TLS em um servidor público.

As decisões de cookies, CSRF e cabeçalhos seguem a [documentação de segurança do Flask](https://flask.palletsprojects.com/en/stable/web-security/).
