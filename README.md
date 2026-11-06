# Radar de Milhas

Site que se atualiza sozinho duas vezes por dia com ofertas de compra de milhas.

## Como colocar no ar (15 minutos, sem custo)
1. Crie um repositório no GitHub e envie estes arquivos (mantenha a pasta `.github`).
2. Em **Settings > Pages**, escolha *Deploy from a branch*, branch `main`, pasta `/docs`.
3. Em **Actions**, abra "Atualizar ofertas" e clique em **Run workflow** para gerar a primeira versão.
4. Seu site fica em `https://SEU-USUARIO.github.io/NOME-DO-REPO/`.

## Antes de ligar: confira os feeds
Abra cada endereço de `FEEDS` em `fetch_offers.py` no navegador. Se mostrar XML, funciona. Se não, procure o link de RSS do site e troque. Você pode adicionar mais blogs e sites de programas.

## Ajustes comuns
- `DAYS`: quantos dias de ofertas mostrar.
- `PROGRAMS`: programas reconhecidos pelo nome.
- `OFFER`/`TOPIC`: palavras que decidem o que é oferta.

## Limites
- O filtro olha só o título, então pode deixar passar ou incluir itens errados.
- Ofertas que só existem no app ou em e-mails não aparecem.
- O site mostra título e link, nunca o texto das matérias.
