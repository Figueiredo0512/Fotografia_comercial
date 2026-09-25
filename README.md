# Fotografia gastronômica — Hortolândia

Site de apresentação e contato em HTML/CSS, com servidor Flask e painel administrativo local. Portfólio gastronômico em construção; os espaços de imagens estão explicitamente identificados. Contato por e-mail e WhatsApp, além de link para o trabalho de fotografia esportiva.

## Executar localmente

Na pasta do repositório, execute:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py serve --port 8081
```

Abra http://127.0.0.1:8081. Administração: http://127.0.0.1:8081/admin/. Para encerrar o servidor, use Control+C. Consulte [ADMINISTRACAO.md](ADMINISTRACAO.md) para detalhes.

## Organização

- `index.html`: conteúdo, navegação e contatos.
- `styles.css`: paleta, layout responsivo e rolagem suave.
- `LEIA-ME.md`: manutenção e próximas etapas.
- `server.py`, `templates/` e `admin.css`: servidor local e painel.
- `ADMINISTRACAO.md`: operação local e limites da versão.
- `test_auth.py`: testes do painel sem envio de mensagens.

## Fluxo de alterações

`main` contém a versão aprovada. Para cada evolução, criar uma branch `feature/descricao` ou `fix/descricao` a partir da `main` atualizada. Validar localmente e abrir um pull request com resumo e verificações. A integração à `main` só ocorre após aprovação explícita da pessoa responsável pelo projeto. Não usar force push na `main`.

Publicar código no GitHub não publica o site na internet. Hospedagem e domínio serão definidos em uma etapa posterior.
