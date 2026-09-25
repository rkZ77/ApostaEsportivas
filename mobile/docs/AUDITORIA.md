# Auditoria · App Pick IA (Android + iOS)

Data: 25/09/2026 · branch `dev` a partir de `df2bc229`.

Ponto de partida: **o app já existe** em `mobile/` (Expo SDK 57, React Native
0.86, TypeScript, expo-router), criado no commit `c9599805`. Esta auditoria
não recomeça do zero: mede o que já está pronto, o que está errado e o que
falta para chegar às lojas.

---

## 1. Estrutura do repositório

```
ApostaEsportivas/        motor de picks (Python) · coleta, IA, pipelines
  src/engine_pipelines/  um pipeline por produto (vip, dica, multipla, faltas,
                         player_stats, boost, alavancagem, bingo, live)
  src/services/          settlement, odds, estatísticas, checagem de resultado
website/backend/         API FastAPI · a mesma para site e app
  routers/               16 routers, ~250 rotas (admin incluso)
website/frontend/        site React + Vite + Tailwind
website/android-twa/     config do TWA antigo (wrapper do site) · não publicado
mobile/                  app nativo Expo
Dockerfile, railway.json deploy único no Railway (site + API + motor)
.github/workflows/ci.yml backend, motor e frontend · o app ainda não tem job
```

## 2. Frontend do site

React 18 + Vite + TypeScript + Tailwind. Sessão por cookie httpOnly. Login
protegido por Cloudflare Turnstile. Rotas públicas relevantes para o app:
`/privacidade`, `/termos`, `/planos`, `/resultados`, `/p/:tipo/:id`.

## 3. Backend

FastAPI (Python 3.12), servido pelo uvicorn no Railway. O mesmo processo
serve o SPA buildado. **Não há scheduler desde 01/08/2026**: geração e
liquidação de picks são disparadas manualmente pelo admin
(`POST /api/admin/run-pipeline`, `/resolve-picks`). O Motor Ao Vivo roda em
laço no processo e é reconciliado no startup.

## 4. Banco

PostgreSQL no Supabase (pooler), acesso por `psycopg2` com pool próprio
(`database.py`). Migrações idempotentes no startup (`migrations.py`).
Atenção: sem `DB_HOST` definido, `get_connection()` cai no banco de
**produção** (documentado em `mobile/README.md`).

## 5. Autenticação

- JWT HS256: access 12 h, refresh 30 dias (`auth_utils.py`).
- Site: cookies httpOnly. App: `Authorization: Bearer`, aceito por
  `get_current_user` como fallback.
- Com o header `X-Client-Platform: android|ios`, login, cadastro, Google e
  refresh devolvem os tokens também no corpo (`_tokens_no_corpo`). Sem o
  header, o site não vê diferença.
- Sessão única: novo login invalida a sessão anterior e responde
  `401 SESSION_INVALIDATED|<dispositivo>`. O app já trata isso.
- Plano e expiração são relidos do banco a cada requisição (não confiam no JWT).
- Google: `POST /api/auth/google` aceita `credential` (ID token) pensado para o app.
- Recuperação: `forgot-password` envia **código de 6 dígitos** válido por
  15 min; `reset-password {email, code, new_password}` troca a senha e derruba
  as sessões abertas. Senha mínima: 10 caracteres.
- Exclusão: `POST /api/auth/delete-account {current_password, confirmacao:"EXCLUIR"}`
  anonimiza a conta e mantém a trilha fiscal.
- **Captcha**: `login` e `register` exigem `captcha_token` do Turnstile
  sempre que `TURNSTILE_SECRET_KEY` está definida (produção). Ver risco T1.

## 6. Endpoints que o app usa ou vai usar

Todas as rotas abaixo já existem. Prefixo `/api`.

| Área | Rotas | Permissão |
|---|---|---|
| Auth | `auth/login`, `register`, `refresh`, `logout`, `me`, `google`, `forgot-password`, `reset-password`, `delete-account`, `profile` (PUT), `activate-trial` | pública / logado |
| Picks do dia | `suggestions/today` (chaves `dica_do_dia`, `vip`, `multiplas`, `alavancagem`, `faltas`, `goleiros`, `player_stats`, `boost`, `bingo`) | logado · backend corta por plano |
| Detalhe | `suggestions/{id}/detail?pick_type=`, `suggestions/{id}/analise`, `/market-form`, `/amostra` | logado |
| Histórico | `suggestions/history`, `recent-results`, `results`, `results/monthly`, `results/games`; `public/results`, `public/profit-curve` | logado / público |
| Múltiplas | `suggestions/multiplas`, `suggestions/alavancagem`, `alavancagem/today` | assinante |
| Ao vivo | `live-picks/feed`, `{id}/detail`, `stats`, `em-leitura`; `live/live-stats`, `live/fixture/{id}/live-stats` | Pro |
| Banca | `banca` (GET), `summary`, `follow` (POST/DELETE), `setup`, `deposit`, `withdraw`, `unidade`, `cashout`, `monthly-close(s)`, `fechamentos/resumo` | logado |
| Planos | `payments/plans` (público), `payments/history` | público / logado |
| Notificações | `notifications` (GET), `{id}/read`, `read-all`; `personal/alerts` (GET/PUT) | logado |
| Push | `notifications/subscribe` · **só Web Push** (endpoint + p256dh/auth) | logado |
| Público | `public/today-summary`, `public/pick/{tipo}/{id}` | público |

Erros: `detail` em português no corpo, 401 (sessão), 403 (plano), 429
(rate limit), 400 (validação). O app já converte isso em mensagem de tela.

## 7. Como os picks são gerados

O motor (`ApostaEsportivas/src/engine_pipelines/*`) grava cada produto na sua
tabela: `picks_vip`, `picks_free` (Dica do Dia), `picks_multiplas`,
`picks_alavancagem`, `picks_faltas`, `picks_player_stats`, `picks_goleiros`
(legado), `picks_boost`, `picks_bingo` (só admin), `live_picks`. A liquidação
(`settlement.py`) grava `result`/`profit`. A API só lê. **O app não calcula
nada**: confiança, EV, stake sugerida e resultado chegam prontos.

## 8. Planos

`users.plan ∈ {free, trial, vip, admin}` + `plan_tier ∈ {base, pro}`.
Catálogo em `routers/payments.py::PLANS` (exposto por `GET /payments/plans`):

| Produto | Mensal | Trimestral | Semestral | Anual |
|---|---|---|---|---|
| Pick IA (base) · pré-jogo | 29,90 | 74,90 | 149,90 | 269,90 |
| Pick IA Pro · + Ao Vivo + agente | 39,90 | 99,90 | 199,90 | 359,90 |

Cobrança: **MercadoPago**, pagamento avulso por período (não é assinatura
recorrente), ativação por webhook assinado (`_apply_approved_payment`).
Trial de 2 dias exige contato verificado. "VIP" é só a chave interna: desde
25/09 o site chama o produto de **Picks Premium**.

## 9. Banca

Tudo no backend (`routers/banca.py`): banca inicial, valor da unidade,
seguir/deixar de seguir pick, odd real, cashout, depósito/saque, fechamento
mensal, alavancagem. `GET /banca` já devolve agregados (P&L, ROI, yield,
acerto, sequência) e as entradas. O app só exibe.

## 10. O que já está pronto no app e pode ser reaproveitado

- Cliente HTTP com refresh único, sessão única e mensagens de erro em PT.
- Tokens no Keystore/Keychain (`expo-secure-store`).
- Trava contra apontar build de DEV para produção.
- Abas Início, Picks, Ao vivo, Apostas, Perfil; detalhe de pick; deep links.
- `useDados`: loading/erro/refresh e polling que para em segundo plano.
- Tokens de tema espelhando o site (`#0A0A0C`, `#00CC00`...).
- Ícone, splash, `br.com.pickia.app` nos dois sistemas.

## 11. O que falta criar

| # | Item | Tipo |
|---|---|---|
| A1 | Captcha no login/cadastro (bloqueia produção) | app |
| A2 | Recuperação de senha com código (hoje incompleta) | app |
| A3 | Excluir conta dentro do app (exigência Apple 5.1.1(v)) | app |
| A4 | Links de Termos, Privacidade e aviso 18+ | app |
| A5 | Tirar o botão "comprar no site" no iOS (Apple 3.1.1/3.1.3) | app |
| A6 | Textos "VIP" → "Picks Premium", igual ao site | app |
| A7 | Perfis de build EAS (APK teste, AAB, iOS dev/prod) | config |
| B1 | Múltiplas e Alavancagem (chegam em `/today` e o app ignora) | app |
| B2 | Histórico com filtros | app |
| B3 | Aba Banca completa (evolução, fechamentos) | app |
| B4 | Detalhe do pick com a análise (`/analise`) | app |
| B5 | Ao vivo com estatísticas da partida (`live-stats`) | app |
| B6 | Preferências de alerta (`personal/alerts`) | app |
| C1 | Token de push nativo: tabela + rota + envio FCM/APNs | **backend** |
| C2 | Testes do app (jest-expo) e job no CI | app/CI |
| C3 | Login com Google no app (exige Sign in with Apple no iOS, 4.8) | app+backend |
| C4 | Compra dentro do app (IAP) · decisão de negócio | app+backend |

## 12. Dependências

Já instaladas: expo, expo-router, expo-secure-store, expo-notifications,
axios, lucide-react-native, react-native-svg, reanimated.
A adicionar: `react-native-webview` (captcha), `jest-expo` +
`@testing-library/react-native` (testes). Para gráfico de evolução, usar o
`react-native-svg` que já existe em vez de outra lib.

## 13. Riscos técnicos

- **T1 · Captcha.** Em produção o app não consegue entrar nem cadastrar:
  não manda `captcha_token` e o backend responde 400. Não aparece em DEV
  porque lá a chave não está configurada. Correção sem tocar no backend:
  renderizar o Turnstile numa WebView com `baseUrl` do domínio do site.
  Pular o captcha por header seria anular a proteção para o site também, já
  que qualquer robô consegue mandar o header.
- **T2 · Push.** A tabela de inscrições é Web Push. Token nativo precisa de
  tabela e envio próprios (C1). Não dá pra reaproveitar sem corromper o site.
- **T3 · Sem scheduler.** Picks e resultados dependem de disparo manual. Um
  push de "novo pick" precisa sair do mesmo lugar que publica, não de um cron.
- **T4 · Banco DEV.** Backend local sem as variáveis de DEV abre produção.
- **T5 · TWA x app nativo.** Mesmo id `br.com.pickia.app`: só um dos dois
  pode ir para a Play Store. O nativo substitui o TWA.
- **T6 · Sessão única.** Abrir o app derruba a sessão do site e vice-versa.
  É regra do produto, mas o usuário vai sentir isso a partir do app.
- **T7 · Sem testes no app** e sem job de CI para ele.

## 14. Riscos · Google Play

Política "Real-Money Gambling, Games, and Contests":
https://support.google.com/googleplay/android-developer/answer/9877032

- O app não aceita aposta nem dinheiro, mas palpites esportivos ficam perto
  da categoria. A política proíbe funcionalidade de "suporte ou companhia"
  para apostas em apps não aprovados; ao mesmo tempo, há muitos apps de
  palpites publicados. **Risco médio a alto de rejeição ou exigência extra.**
- Não linkar casa de aposta, não ter anúncio de aposta, não usar "bet",
  "apostar agora" na ficha. Hoje o app só cita o nome da casa onde a odd foi
  vista, sem link. Manter assim.
- Classificação etária 18+ e aviso de jogo responsável.
- Questionário de Data Safety: e-mail, nome, telefone, identificadores de
  push. Link de exclusão de conta **fora do app** também é exigido (URL web).
- Pagamento: vender acesso digital dentro do app exige Google Play Billing
  (ou o programa de faturamento alternativo onde houver). Hoje o app não vende.
- No Brasil, casas de aposta precisam de autorização da SPA/MF (Lei
  14.790/2023). A Pick IA não é casa, mas a portaria de publicidade de apostas
  atinge divulgação. **Vale uma consulta jurídica antes de publicar.**

## 15. Riscos · App Store

Diretrizes: https://developer.apple.com/app-store/review/guidelines/

- **5.3.4**: exige licença só para apps que oferecem aposta com dinheiro.
  Palpites não são isso, mas o revisor pode classificar como "gambling aid".
  Risco médio.
- **3.1.1 / 3.1.3**: liberar conteúdo pago exige In-App Purchase. Assinante
  que comprou no site pode entrar e usar (3.1.3(b)). O app **não pode**
  empurrar para comprar fora, e hoje o Perfil tem "Abrir planos no site":
  motivo quase certo de rejeição. No Brasil, desde junho/2026, link externo
  de pagamento é permitido, com taxa de 15% e **apresentado junto com o IAP**
  ([Apple](https://www.apple.com/newsroom/2026/06/apple-announces-changes-to-ios-in-brazil/)).
  Sem IAP, o caminho seguro é não linkar.
- **5.1.1(v)**: excluir conta dentro do app é obrigatório. Backend já tem;
  falta a tela (A3).
- **4.8**: se o app oferecer login com Google, precisa oferecer Sign in with
  Apple (ou equivalente). Hoje o app só tem e-mail/senha, então não se aplica.
- Classificação 17+/18+, texto de jogo responsável e conta de teste com plano
  ativo para o revisor enxergar o conteúdo.

**Nenhuma das duas lojas garante aprovação.** O que dá pra fazer é tirar os
motivos objetivos de rejeição listados acima.

## 16. Plano por etapas

Cada etapa sai em commits pequenos na `dev`, um assunto por commit.

1. **Bloqueios de loja e de produção** · A1–A7.
2. **Conteúdo** · B1 múltiplas/alavancagem, B4 análise, B2 histórico, B3 banca.
3. **Ao vivo** · B5 estatísticas da partida, com o polling que já existe.
4. **Notificações** · C1 backend de push nativo (proposta antes de mexer) + B6.
5. **Testes e CI** · C2.
6. **Loja** · EAS project, assinatura dos builds, `assetlinks.json`/AASA,
   ficha, screenshots, conta de revisão, página e artes de divulgação.
7. **Decisões de negócio** · C3 Google/Apple login, C4 IAP.

## Arquitetura proposta

Mantém a atual, que já segue o que foi pedido:

```
mobile/
  app/            rotas expo-router (telas)
  src/api/        client, session, endpoints, types  ← única porta para o backend
  src/auth/       AuthContext, rótulo do plano
  src/components/ UI reutilizável e cards
  src/hooks/      useDados (estados de tela, polling)
  src/lib/        formatação (fuso, moeda)
  src/push/       permissão e token
  src/config/     ambiente e trava de produção
  src/theme/      tokens
  docs/           esta auditoria
```

Regra: nenhuma conta de negócio no app. Se um número aparece, veio da API.
