# Legendas dos stories

Story tem legenda curta ou nenhuma: o texto já está desenhado na imagem. O que
está aqui embaixo é o que vai nos **adesivos** (enquete, link, pergunta) e a
frase da caixa de resposta quando ela ajudar.

Três sequências, cada uma publicável sozinha. A ordem dentro da sequência
importa: o número primeiro, o buraco no meio, o convite só no fim.

Os números saem de `fechamento.py`, que lê a rota pública. Se um story for
questionado, a conferência é a mesma URL que está no último quadro.

---

## `setembro-00` a `setembro-04` · o mês correndo

Cinco telas. Publicar em sequência, sem intervalo.

| Tela | O que mostra | Adesivo sugerido |
| --- | --- | --- |
| 00 | +41,52u em 122 picks | nenhum, deixa o número respirar |
| 01 | Dia a dia, com os dois dias negativos | enquete: "Você aguentaria o dia de 02/09?" Sim / Não |
| 02 | 64,6% de acerto | nenhum |
| 03 | Produto por produto, com os que perderam | nenhum |
| 04 | Print da lista de picks | **link para pickia.com.br/resultados** |

Frase da caixa de resposta no story 04: "Abre sem conta. Confere o mês inteiro."

---

## `agosto-00` a `agosto-04` · o fechamento

Publicar no fim do mês, ou como reprise do carrossel de fechamento.

| Tela | O que mostra | Adesivo sugerido |
| --- | --- | --- |
| 00 | +105,65u em agosto | nenhum |
| 01 | ROI de 12,5% sobre 843u | pergunta: "Sabe o que é ROI?" |
| 02 | Produto por produto, o grátis no vermelho | nenhum |
| 03 | Por liga, a Série A tirando 30,48u | nenhum |
| 04 | Print do resumo do mês | **link para pickia.com.br/resultados** |

---

## `dia-00` a `dia-02` · todo dia

A sequência mais curta, e a que se repete. Roda depois que o dia fecha:

```
python fechamento.py 2026-09 --atualizar
python stories.py --sequencia dia
```

O `--atualizar` é obrigatório aqui. Sem ele o story do dia sai com o cache de
ontem, e ninguém percebe até alguém conferir no site.

| Tela | O que mostra | Adesivo sugerido |
| --- | --- | --- |
| 00 | O resultado do dia em unidades | nenhum |
| 01 | Os picks nominais, com green, red e push | nenhum |
| 02 | Convite, com print do histórico | **link para pickia.com.br** |

---

## Regras que valem pros três

**O link vai só no último.** Adesivo de link em todo story treina o leitor a
pular. No último ele já viu o placar e o buraco.

**Nada de "aproveite" nem contagem regressiva.** O produto é histórico
publicado, não oferta.

**O aviso legal já está desenhado na imagem**, no rodapé de todas as telas.
Não precisa repetir na legenda.

**Zona segura:** o texto todo vive fora dos 250px de cima e dos 340px de baixo.
Pra conferir antes de publicar:

```
python stories.py --sequencia setembro --guias
```

As faixas vermelhas marcam o que a interface do Instagram cobre. Nada de texto
pode encostar nelas.

---

## Como virar o mês

```
python fechamento.py 2026-10 --atualizar
python prints.py --url https://pickia.com.br --mes 2026-10 --print mes-lista --print mes-resumo
```

Depois troque o `"mes"` da sequência em `stories.py` e o nome do print do
último quadro. Os `{placeholder}` se atualizam sozinhos.
