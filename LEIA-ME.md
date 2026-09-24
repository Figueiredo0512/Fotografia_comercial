# Site local

Primeira versão estática em HTML e CSS, sem dependências, cadastro ou conexão com serviços externos. Nenhum dado é enviado. Os blocos de imagem estão explicitamente identificados como espaços reservados. O contato oferece e-mail via mailto para figasphoto@gmail.com (sem exibir o endereço no texto) e WhatsApp via https://wa.me/5519992493060 para +55 (19) 99249-3060. A mensagem inicial do WhatsApp é editável e só é enviada quando o visitante confirmar no aplicativo. O Instagram foco.em.movimento está identificado como fotografia esportiva.

## Abrir

Abra `index.html` no navegador diretamente ou execute no Terminal:

```sh
cd Fotografia_comercial
python3 -m http.server 8080 --bind 127.0.0.1
```

Acesse http://127.0.0.1:8080. O servidor atende apenas este computador. Para encerrar, pressione Control+C no Terminal. Se a porta estiver ocupada, use 8081 e abra a URL com essa porta. Não sirva a pasta superior, que contém documentos comerciais internos.

## Editar

- `index.html`: textos, navegação, espaços das fotos e contato.
- `styles.css`: cores, tipografia, espaçamento e adaptação de tela.
- Nenhuma instalação ou etapa de compilação é necessária. Atualize a página depois de salvar.

## Próxima versão

Adicionar fotos próprias autorizadas em uma pasta `imagens`, com texto alternativo descritivo, dimensões reservadas, tamanhos responsivos e carregamento adiado abaixo da primeira tela. Preservar os originais fora da pasta do site e remover localização dos arquivos públicos. O destino do contato foi conferido no HTML; entrega de e-mail depende do aplicativo configurado pelo visitante. Atualizar marca e apresentação. Conferir todas as larguras e o peso novamente com fotos reais.

A página está com `noindex, nofollow` por ser uma prévia incompleta. Quando houver uma etapa de publicação autorizada, revisar esse marcador, remover o aviso de prévia, conferir direitos de uso, contato, hospedagem e domínio. O código estático pode ser aproveitado na hospedagem futura; provedor e serviços pagos permanecem a definir.
