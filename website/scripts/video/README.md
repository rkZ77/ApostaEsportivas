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

  Padrão: `pt-BR-ThalitaMultilingualNeural`. Troque com `--voz`; as opções
  saem em `python narracao.py --vozes`. Mas o maior culpado por voz soando de
  robô quase nunca é a voz · é o texto. Frase longa e simétrica de anúncio
  entrega na hora. A narração aqui é escrita pra ser FALADA: frase curta,
  "pra" no lugar de "para", nada de tríade publicitária.
- **ffmpeg** monta. Tem que ser o completo: o que vem junto do Playwright é
  build reduzida (`--disable-everything`, só webm/vp8) e não faz H.264, AAC
  nem mp4. `ferramentas.py` acha o binário mesmo antes de reiniciar o shell.

## Login: por que é manual (e por que vai continuar sendo)

As cenas `banca`, `pegar-pick`, `acompanhar` e `agente` precisam de sessão VIP.
**Não existe login automatizado aqui, e não é limitação do script:**
`/api/auth/login` e `/api/auth/register` passam por `_verify_captcha`, e o
Turnstile detecta navegador instrumentado. Medido no noprod: a Cloudflare
devolve 401 no endpoint de challenge e nenhum token é emitido, headless ou com
janela aberta, mesmo esperando 40 segundos. Isso é o anti-bot funcionando; não
tente contornar.

O caminho é não passar pelo captcha. Você loga uma vez, à mão, e a sessão é
reaproveitada:

```
python gravar.py --url https://SEU-NOPROD --login-manual
```

Abre um navegador de verdade, você entra normalmente (resolvendo o captcha) e
a sessão é gravada em `sessao.json`. Depois disso as cenas rodam sozinhas.

Dois detalhes que economizam raiva:

- O backend guarda um `session_token` **único por usuário**. Logar de novo em
  outro lugar derruba a sessão salva. Grave logo depois de salvar.
- `sessao.json` é credencial. Está no `.gitignore`, e é bom que continue.

Se quiser uma conta demo dedicada em vez da sua, crie pelo painel admin
(`POST /api/admin/users`, com `plan: "vip"` · sem `plan_expires_at` o VIP não
expira). Pelo admin não precisa de CPF nem passa por captcha.

## Uso

```
python narracao.py --vozes                    lista as vozes disponíveis
python narracao.py --todas --voz pt-BR-FranciscaNeural
python gravar.py --listar
python gravar.py --url https://SEU-NOPROD --login-manual     uma vez só
python gravar.py --url https://SEU-NOPROD --todas
python gravar.py --url https://SEU-NOPROD --cena banca --ver  navegador visível
python montar.py --todas --musica trilha.mp3
```

`PICKIA_URL` funciona no lugar do `--url`.

| pasta | conteúdo |
|---|---|
| `voz/` | mp3 da narração e `tempos.json` |
| `saida/` | `.webm` cru de cada cena e as marcas de tempo |
| `cartoes/` | png de abertura e fecho |
| `pronto/` | **o mp4 final** |

## Por que a gravação é 540x960 e o mp4 é 1080x1920

O Playwright captura em **pixels CSS** e ignora o `device_scale_factor`. Ele
também só reduz a imagem pra caber em `record_video_size`, nunca amplia. Pedir
1080x1920 na gravação fazia a página sair desenhada 1:1 no canto superior
esquerdo de um quadro cinza.

Então a cena é gravada em 540x960 (9:16 exato, e abaixo do breakpoint `sm` de
640px do Tailwind, o que garante o layout mobile) e o `montar.py` amplia num 2x
exato com lanczos. Mexeu no `VIEWPORT` de `estudio.py`? Ajuste junto o tamanho
da fonte da legenda, que está calibrado pra esse quadro.

O gravador também aceita os cookies via localStorage antes da página nascer e
fecha a barra "Testar o VIP por 2 dias" a cada navegação · as duas são `fixed
bottom-0` e cobriam exatamente a faixa da legenda.

## Cenas

Cada cena é um vídeo de **um assunto só**, entre 25 e 40 segundos. Vídeo longo
cobrindo tudo foi testado e descartado: dava 70 segundos e ninguém termina.

| nome | conteúdo | login |
|---|---|---|
| `convite` | chamada: você aposta no escuro? | não |
| `cadastro` | criar conta grátis em 1 minuto | não |
| `como-funciona` | de onde vem o pick | não |
| `resultados` | o histórico aberto | não |
| `banca-config` | configurar a banca do zero | sim |
| `pick-abrir` | abrir um pick e ver a análise | sim |
| `pick-registrar` | registrar a aposta e o stake | sim |
| `meus-picks` | acompanhar suas apostas | sim |
| `minha-banca` | a evolução da sua banca | sim |
| `agente` | conversar com o Agente IA | sim |

## Carrosséis pro feed

```
python carrossel.py --listar
python carrossel.py --todos
```

PNG 1080x1350 (4:5, o formato que ocupa mais altura no feed) em `carrossel/`.
Três carrosséis de 7 slides: `como-funciona`, `banca`, `pegar-pick`. Capa,
cinco slides de conteúdo e um de chamada pra ação. O texto vive em
`CARROSSEIS`, no topo de `carrossel.py`.

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
