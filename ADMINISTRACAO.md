# Administração local

Branch: `feature/login-admin`. O painel exige e-mail, senha e um código enviado ao e-mail do administrador. Não há contas ou senhas padrão.

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

O fluxo é: `/admin/cadastro` cria um usuário; `/admin/login` recebe e-mail e senha; `/admin/verificar` recebe o código de seis dígitos; `/admin/` abre agenda e portfólio após as duas etapas. O código expira em dez minutos e a sessão em uma hora. O botão **Sair** encerra a sessão.

Não há bloqueio por quantidade de tentativas de e-mail e senha. O código de confirmação continua limitado a cinco tentativas por solicitação e expira em dez minutos.

O cadastro solicita nome, sobrenome, e-mail com confirmação, senha com confirmação e cidade. A senha precisa ter pelo menos 8 caracteres e fica armazenada somente como hash. O e-mail não pode ser repetido. Nesta versão local, qualquer pessoa com acesso ao endereço do servidor pode abrir a página de cadastro; antes de uma hospedagem pública, será necessário restringir novos cadastros por convite ou aprovação administrativa.

O botão **Esqueci minha senha** abre `/admin/esqueci-senha`. O usuário informa o e-mail, recebe um código válido por dez minutos e define uma nova senha em `/admin/redefinir-senha`. A troca encerra as sessões anteriores dessa conta. O envio depende da mesma configuração SMTP usada pelo código de login e aceita até três solicitações por conta em 15 minutos.

## Dados locais

Banco, fotos, chave de sessão e configuração SMTP ficam em **`.fotografia-admin/`, na pasta acima de `site/`**, fora do repositório e das rotas públicas. Não copie essa pasta para o GitHub.

## Agenda de visitas

No painel, a seção **Agenda de visitas** mostra o mês selecionado e permite avançar ou voltar entre meses. O botão **Nova visita** abre um pop-up para escolher entre reunião e ensaio, registrar estabelecimento, data e horário em intervalos de cinco minutos. Em ensaios, o campo de equipamentos é obrigatório. Clique em um evento para abrir sua ficha, editar os dados ou excluí-lo. Os compromissos ficam na tabela `visits` do banco local e são consultados apenas pelo servidor local.

## Portfólio local

Use **Editar foto** na biblioteca para alterar título, descrição ou substituir a imagem. **Esconder foto** retira a imagem da home, da galeria e do endereço público do arquivo, mantendo-a no painel. Desmarque para exibir novamente. **Excluir foto** abre uma confirmação e remove o cadastro e o arquivo; substituir a imagem também remove o arquivo anterior.

O menu superior oferece acesso à página **Portfólio**. Nela é possível enviar fotografias JPEG, PNG ou WebP de até 12 MB, com título e descrição. Os arquivos ficam em `.fotografia-admin/portfolio/` e os dados de organização ficam na tabela `portfolio_images` do banco local. Essa pasta não deve ser enviada ao GitHub.

O item **Usuários** abre `/admin/usuarios` e lista nome, e-mail, cidade e data de cadastro das contas com acesso ao painel. Senhas, hashes, códigos e credenciais SMTP não são exibidos.

As cinco fotografias mais recentes aparecem automaticamente no carrossel da página inicial. O sexto card, **Ver mais**, abre `/portfolio`, onde todas as imagens cadastradas são apresentadas. Enquanto houver menos de cinco fotos, os lugares restantes continuam marcados como espaços reservados.

## Verificação

```sh
.venv/bin/python -m unittest -v test_auth
```

Os testes usam banco temporário e transporte de e-mail simulado. Verificam cadastro, senha mínima, recuperação de senha, login em duas etapas, proteção das rotas administrativas, calendário, portfólio, cabeçalhos de segurança e bloqueio de arquivos privados. Nenhuma mensagem real é enviada pelos testes.

## Hospedagem futura

Esta execução é local, com Flask sem modo debug. Para hospedar será preciso escolher servidor WSGI, armazenamento persistente, HTTPS, cookies Secure, domínio permitido e configuração de e-mail de produção. As definições atuais de host são restritas a localhost/127.0.0.1. Não expor este servidor local à internet.

As decisões de cookies, CSRF e cabeçalhos seguem a [documentação de segurança do Flask](https://flask.palletsprojects.com/en/stable/web-security/).
