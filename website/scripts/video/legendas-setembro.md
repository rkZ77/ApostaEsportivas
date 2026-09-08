# Legendas de setembro de 2026

Dois carrosséis, dois reels e as três sequências de stories. Os números saem
de `fechamento.py`, que lê a rota pública, e o mês ainda está correndo: se for
publicar depois de virar o mês, rode `python fechamento.py 2026-09 --atualizar`
e regere, senão o post afirma um número que o site já não mostra.

---

## Carrossel 1 · `setembro-00` a `setembro-06`

**Legenda**

Setembro vai em +41,52u, e o mês ainda nem acabou.

122 picks resolvidos em 6 dias, espalhados por 14 ligas. 71 green, 38 red, ROI
de 10%.

Não é print de bilhete escolhido a dedo. É o mês inteiro, do jeito que está
publicado, com os dois dias que fecharam no vermelho no meio.

A Série B puxa o resultado com +13,96u. A Série A, que é a liga mais coberta do
site, está devendo 5,69u. As duas coisas estão na mesma tela, filtráveis por
liga e por mês.

Confira em pickia.com.br/resultados. Abre sem conta e sem cartão.

Aposta é entretenimento para maiores de 18 anos. Nenhum resultado passado
garante resultado futuro.

**Hashtags**
#apostasesportivas #apostaesportiva #tipsfutebol #valuebet #gestaodebanca
#futebol #brasileirao #serieb #tipster #apostasonline

---

## Carrossel 2 · `setembro-produtos-00` a `setembro-produtos-06`

**Legenda**

O ao vivo carregou setembro. E dois produtos estão no vermelho.

Radar Ao Vivo: +40,58u em 56 picks, 71,4% de acerto.
Pick VIP: +13,84u em 22 picks, ROI de 15,7%.
Pick Boost: +1,91u, com 75% de acerto. Odd baixa rende pouco mesmo acertando.
Números do Jogador: -10,29u. É o pior produto do mês.
Pick do Dia, o grátis: -2,64u.

O produto de jogadores perdeu dinheiro em setembro. Está lá, na mesma tela, com
o mesmo tamanho de fonte do que deu lucro.

Um placar que só tem green não é placar, é anúncio.

pickia.com.br/resultados, com filtro por produto.

Aposta é entretenimento para maiores de 18 anos.

**Hashtags**
#apostasesportivas #valuebet #tipsfutebol #transparencia #gestaodebanca
#apostaesportiva #tipster #futebol #roi #apostasonline

---

## Reels 1 · `pronto/reels-setembro.mp4` (36s)

Cinco quadros narrados: o número do mês, o dia a dia com os dois dias
negativos, o acerto, os produtos e o convite.

**Legenda**

Setembro está em +41,52u, e os dias ruins estão no vídeo.

122 picks resolvidos, 71 green, 38 red. O histórico inteiro abre sem conta em
pickia.com.br/resultados.

Aposta é entretenimento para maiores de 18 anos.

**Capa sugerida:** o primeiro quadro, que já é o número grande.

---

## Reels 2 · `pronto/reels-dia.mp4` (19s)

O curto, para repetir todo dia depois que a rodada fecha.

**Legenda**

O dia fechou em +11,08u.

Os picks estão no vídeo com a odd que estava valendo e o resultado de cada um,
inclusive os que perderam.

Tem pick grátis todo dia em pickia.com.br.

Aposta é entretenimento para maiores de 18 anos.

---

## Stories

Ver `legendas-stories.md`. As três sequências (`setembro`, `agosto`, `dia`) e
os adesivos sugeridos estão lá.

---

## Como regerar tudo

```
python fechamento.py 2026-09 --atualizar
python prints.py --url https://pickia.com.br --mes 2026-09 --todos
python carrossel.py --carrossel setembro --carrossel setembro-produtos
python stories.py --todos
python reels.py --todos
```

O `reels.py` reusa os mp3 que já existem. Mudou uma fala, rode com
`--forcar-voz`, senão ele monta com a narração antiga e o vídeo fica dizendo
uma coisa enquanto a tela mostra outra.

Para virar o mês: troque o `"mes"` das entradas em `carrossel.py`,
`stories.py` e `reels.py`, e o sufixo dos prints (`mes-lista-2026-09` vira
`mes-lista-2026-10`). Os `{placeholder}` se atualizam sozinhos; as falas dos
reels citam os números por extenso e precisam ser reescritas à mão.
