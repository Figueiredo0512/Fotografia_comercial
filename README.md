# Fotografia gastronômica — Hortolândia

Site estático de apresentação e contato, em HTML e CSS. Portfólio gastronômico em construção; os espaços de imagens estão explicitamente identificados. Contato por e-mail e WhatsApp, além de link para o trabalho de fotografia esportiva.

## Executar localmente

Na pasta do repositório, execute:

```sh
python3 -m http.server 8080 --bind 127.0.0.1
```

Abra http://127.0.0.1:8080. Também é possível abrir `index.html` diretamente no navegador. Não há dependências ou compilação. Para encerrar o servidor, use Control+C.

## Organização

- `index.html`: conteúdo, navegação e contatos.
- `styles.css`: paleta, layout responsivo e rolagem suave.
- `LEIA-ME.md`: manutenção e próximas etapas.

## Fluxo de alterações

`main` contém a versão aprovada. Para cada evolução, criar uma branch `feature/descricao` ou `fix/descricao` a partir da `main` atualizada. Validar localmente e abrir um pull request com resumo e verificações. A integração à `main` só ocorre após aprovação explícita da pessoa responsável pelo projeto. Não usar force push na `main`.

Publicar código no GitHub não publica o site na internet. Hospedagem e domínio serão definidos em uma etapa posterior.
