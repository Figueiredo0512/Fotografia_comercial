# Site local

Página pública em HTML e CSS, com servidor Flask nesta branch para acesso administrativo. O login envia código por e-mail quando o SMTP estiver configurado. Os blocos de imagem estão explicitamente identificados como espaços reservados. O contato oferece e-mail via mailto para figasphoto@gmail.com (sem exibir o endereço no texto) e WhatsApp via https://wa.me/5519992493060 para +55 (19) 99249-3060. A mensagem inicial do WhatsApp é editável e só é enviada quando o visitante confirmar no aplicativo. O Instagram foco.em.movimento está identificado como fotografia esportiva.

## Abrir

Siga o cadastro e a instalação de [ADMINISTRACAO.md](ADMINISTRACAO.md). Depois, na pasta do repositório:

```sh
.venv/bin/python server.py serve --port 8081
```

Acesse http://127.0.0.1:8081; o login fica em `/admin/login`. O servidor atende apenas este computador. Para encerrar, pressione Control+C no Terminal. Não sirva o repositório nem a pasta superior usando servidor estático: use o servidor Flask, que só entrega rotas públicas permitidas.

## Editar

- `index.html`: textos, navegação, espaços das fotos e contato.
- `styles.css`: cores, tipografia, espaçamento e adaptação de tela.
- Instalação Python descrita em ADMINISTRACAO.md; sem compilação de frontend. Atualize a página depois de salvar HTML/CSS; reinicie o servidor depois de alterar Python ou configurar SMTP.

## Próxima versão

Adicionar fotos próprias autorizadas em uma pasta `imagens`, com texto alternativo descritivo, dimensões reservadas, tamanhos responsivos e carregamento adiado abaixo da primeira tela. Preservar os originais fora da pasta do site e remover localização dos arquivos públicos. O destino do contato foi conferido no HTML; entrega de e-mail depende do aplicativo configurado pelo visitante. Atualizar marca e apresentação. Conferir todas as larguras e o peso novamente com fotos reais.

A página está com `noindex, nofollow` por ser uma prévia incompleta. Quando houver uma etapa de publicação autorizada, revisar esse marcador, remover o aviso de prévia, conferir direitos de uso, contato, hospedagem e domínio. O código estático pode ser aproveitado na hospedagem futura; provedor e serviços pagos permanecem a definir.
