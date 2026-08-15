# Vídeos curtos do Pick IA

Grava o site rodando de verdade e entrega um **mp4 1080x1920 com voz, legenda,
cartão de abertura, transições e chamada pra ação**, pronto pra publicar no
Instagram, TikTok ou Shorts.

## O fluxo, em três passos

A ordem importa. Cada passo depende do anterior.

```
1. python narracao.py --todas          gera a voz e mede a duração de cada fala
2. python gravar.py   --todas --url …  grava a tela segurando o tempo de cada fala
3. python montar.py   --todas          junta cartões, transições, voz e exporta mp4
```

O truque que faz áudio e imagem baterem: a narração é gerada **primeiro**. A
duração real de cada mp3 é o que define quanto tempo a tela segura em cada
fala, e a gravação anota em que segundo cada uma começou
(`saida/<cena>.marcas.json`). A montagem só desloca esses instantes pelo tempo
do cartão de abertura. Ninguém ajusta áudio na mão · se você mudar uma frase,
rode `narracao.py` de novo e regrave, que o encaixe se refaz sozinho.

## Instalação

Tudo já está instalado nesta máquina. Pra refazer em outra:

```
pip install playwright edge-tts
python -m playwright install chromium
winget install Gyan.FFmpeg
```

- **playwright** grava a tela e desenha os cartões.
- **edge-tts** faz a voz. Usa as vozes neurais do Edge, que são boas o
  bastante pra publicar e **não pedem conta nem chave de API**. A única voz
  pt-BR instalada no Windows é a "Microsoft Maria Desktop", robótica demais.
- **ffmpeg** monta. Tem que ser o completo: o que vem junto do Playwright é
  build reduzida (`--disable-everything`, só webm/vp8) e não faz H.264, AAC
  nem mp4. `ferramentas.py` acha o binário mesmo antes de reiniciar o shell.

## Conta demo

As cenas `banca`, `pegar-pick`, `acompanhar` e `agente` precisam de login VIP.
Crie a conta pelo painel admin (`POST /api/admin/users`), com `plan: "vip"` ·
sem `plan_expires_at` o VIP não expira. A senha precisa de 10+ caracteres, uma
maiúscula e um número, mesma política do cadastro público.

Essa conta é a **única** coisa que o processo escreve no banco, e é uma linha
em `users`.

## Uso

```
python narracao.py --vozes                    lista as vozes disponíveis
python narracao.py --todas --voz pt-BR-FranciscaNeural
python gravar.py --listar
python gravar.py --url https://SEU-NOPROD --todas --usuario demo@… --senha …
python gravar.py --url https://SEU-NOPROD --cena banca --ver     navegador visível
python montar.py --todas --musica trilha.mp3
```

Variáveis de ambiente no lugar das flags:

```
PICKIA_URL=https://SEU-NOPROD
PICKIA_DEMO_USER=demo@pickia.com.br
PICKIA_DEMO_SENHA=Demo123456
```

| pasta | conteúdo |
|---|---|
| `voz/` | mp3 da narração e `tempos.json` |
| `saida/` | `.webm` cru de cada cena e as marcas de tempo |
| `cartoes/` | png de abertura e fecho |
| `pronto/` | **o mp4 final** |

## Cenas

| nome | conteúdo | login |
|---|---|---|
| `convite` | chamada pra conhecer o site e criar conta | não |
| `visao-geral` | o que o site faz, de ponta a ponta | não |
| `banca` | configurar a banca do zero | sim |
| `pegar-pick` | pegar um pick e abrir "Entenda esta análise" | sim |
| `acompanhar` | meus picks, minha banca e resultados | sim |
| `agente` | conversar com o Agente IA | sim |

## O que o gravador NÃO faz no banco

noprod aponta pro banco de **produção**, então isso é regra dura, não zelo:

- Todo `POST`/`PUT`/`PATCH`/`DELETE` de setup de banca, follow de pick, saque,
  reset de mês e cadastro é interceptado e devolvido como 204 sem chegar no
  servidor (`Estudio.bloquear_escrita`).
- `/banca` e `/meus-picks` são servidos por fixture (`fixtures.py`), não por
  conta real. Motivo: `GET /api/leaderboard` monta o ranking público a partir
  de `user_followed_picks` sem filtro de conta de teste, e bastam 3 picks
  resolvidos pra uma conta demo aparecer no ranking que os assinantes veem.
- O resto da tela é dado **real** de produção: home, picks do dia, a análise
  de cada pick, resultados, estatísticas.

A única exceção deliberada é `POST /api/chat`, na cena do agente: ela conversa
com o agente de verdade porque é o que a cena demonstra. Não grava nada, mas
consome tokens. Use `--chat-fake` pra uma resposta canned e determinística.

## A banca do vídeo

`fixtures.py` monta uma banca de R$ 500 com unidade de R$ 25 (5%), 20 apostas
em três semanas: R$ 565,25 no fim, ROI 13,1%, yield 7,5%, acerto 61%.

Os números saem da mesma aritmética de `_compute_follow_pnl` em
`routers/banca.py`, então tudo que aparece na tela fecha: gráfico, saldo, ROI e
yield vêm da mesma lista de apostas. Pra mexer, edite a `_SEMENTE` e rode
`python fixtures.py` pra conferir · a primeira calibragem dava 65% de ROI, que
não é número pra pôr em vídeo de captação.

## Editar texto e design

- **Narração e legenda** ficam em `NARRACAO`, no topo de `cenas.py`. Cada
  entrada é `(o que a voz fala, o que aparece escrito)`. São textos diferentes
  de propósito: a voz conta a história inteira, a legenda é o resumo que ainda
  funciona com o som desligado, que é como boa parte do Instagram assiste.
- **Cartões** ficam em `CARTOES`, no mesmo arquivo, e o desenho em
  `cartoes.py`. As cores saem dos tokens do site (`frontend/src/index.css`):
  fundo `#0a0a0c`, verde da marca `#00CC00`.
- As falas terminadas em `-fecho` não são chamadas por nenhuma cena: a
  montagem encaixa cada uma por cima do cartão final, e o cartão cresce
  sozinho pra caber a fala inteira.

## Ajustar uma cena

Cenas vivem em `cenas.py`, uma função cada. O vocabulário é curto:

```python
e.ir("/picks")                        # navega
fala(e, "pick-01")                    # narra e segura o tempo real do áudio
e.rolar(400, ms=1000)                 # rolagem suave
e.rolar_ate("text=Ver histórico")     # rola até o elemento
e.apontar("button.algo")              # leva o cursor sem clicar
e.tocar("button:has-text('Apostar')") # aponta, pausa e clica
e.digitar("#reg-email", "a@b.com")    # clica e digita com atraso humano
e.legenda(None)                       # apaga a legenda
```

`tocar`, `digitar` e `rolar_ate` devolvem `False` em vez de estourar quando o
seletor não existe, pra uma mudança de texto no front não derrubar a gravação
inteira · aparece `[aviso]` no console e a cena segue.

## Se a cena `pegar-pick` sair vazia

A janela do motor é só **hoje**. Sem pick publicado no dia, `/picks` está vazia
e a cena avisa e encerra. Grave num dia com picks no ar.

## Trilha sonora

`--musica trilha.mp3` entra bem baixa (9%) por baixo da narração. Não vem
trilha junto: use uma faixa que você tenha direito de publicar, senão o
Instagram silencia o vídeo.
