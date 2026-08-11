# Pick IA · App mobile (Android + iOS)

App nativo em React Native + Expo. **Não é um WebView**: é uma interface
própria para celular que consome o mesmo backend, as mesmas APIs e o mesmo
motor de picks do site.

```
                    PICK IA
                       |
                MOTOR DE PICKS
                  ÚNICO/CENTRAL
                       |
          +------------+------------+
          |            |            |
         WEB         ANDROID       IOS
          |            |            |
          +------------+------------+
                       |
                  website/backend
```

O app **não** tem motor, não tem IA e não recalcula nada. Confiança, EV,
stake, resultado e liberação por plano chegam prontos do backend. Se um
número aparece na tela, ele veio de `website/backend/routers/`.

## Rodar em DEV

Precisa de **duas coisas no ar**: o backend e o Metro.

### 1. Backend apontando para o banco DEV

Atenção: `database.get_connection()` cai em `DB_HOST_PROD` quando `DB_HOST`
não está definido. Não existe uma chave `DB_ENV` que troque isso sozinha —
**as variáveis DEV precisam ser passadas explicitamente**, senão o backend
local abre produção.

Da raiz do repositório, usando os valores de `.env.dev`:

```bash
cd website/backend

DB_HOST="$DB_HOST_DEV" DB_PORT="$DB_PORT_DEV" DB_NAME="$DB_NAME_DEV" \
DB_USER="$DB_USER_DEV" DB_PASS="$DB_PASS_DEV" DB_SSLMODE=require \
APP_ENV=development SIDE_EFFECTS=off \
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Por que cada uma:

- `--host 0.0.0.0` · sem isso o celular na mesma rede não enxerga o backend
  (`localhost` de dentro do aparelho é o próprio aparelho).
- `SIDE_EFFECTS=off` · impede que a instância local suba o scheduler e passe
  a gerar picks, resolver resultados e mandar e-mail de verdade. Ver
  `website/backend/runtime_env.py`.
- `APP_ENV=development` · cookies sem `secure`, como no dev do site.

### 2. O app

```bash
cd mobile
npm install
npm run android      # emulador ou aparelho via USB
```

A URL da API é descoberta sozinha a partir do Metro: no emulador vira
`10.0.2.2:8000`, no celular físico vira o IP da sua máquina na LAN. Trocar de
aparelho não pede reconfiguração. Para forçar outro endereço, copie
`.env.example` para `.env`.

O ambiente em uso aparece na tela de login e no Perfil. Apontar um build de
desenvolvimento para `pickia.com.br` é recusado por `src/config/env.ts`.

## Estrutura

```
app/                      rotas (expo-router · o arquivo é a rota)
  _layout.tsx             tema, sessão e a guarda de navegação
  (auth)/                 login, cadastro, recuperação de senha
  (tabs)/                 Início, Picks, Ao vivo, Apostas, Perfil
  pick/[id].tsx           pick individual · destino dos deep links
src/
  api/                    cliente HTTP, sessão no keystore, endpoints tipados
  auth/                   AuthContext (espelho do contexto do site)
  components/             primitivos de UI e os cards de pick
  config/env.ts           resolução da API e a trava contra produção
  hooks/useDados.ts       carregamento, refresh e polling preso ao foco
  lib/formato.ts          formatação · inclui a regra de fuso do projeto
  push/                   permissão e token do aparelho
  theme/tokens.ts         espelho dos tokens de index.css
```

## O que o app consome

Nenhum endpoint foi criado para o app. Todos já existiam:

| Tela | Endpoint |
|---|---|
| Início | `GET /api/suggestions/today`, `GET /api/public/today-summary`, `GET /api/banca` |
| Picks | `GET /api/suggestions/today` |
| Ao vivo | `GET /api/live-picks/feed` |
| Pick individual | `GET /api/suggestions/{id}/detail`, `GET /api/live-picks/{id}/detail` |
| Minhas Apostas | `GET /api/banca` |
| Autenticação | `POST /api/auth/login`, `/register`, `/refresh`, `/logout`, `GET /api/auth/me` |

## Autenticação

O site usa cookie httpOnly. O app não tem cookie jar confiável entre
reinícios, então guarda o token no Keystore (Android) / Keychain (iOS) via
`expo-secure-store` e o envia como `Authorization: Bearer`.

`auth_utils.get_current_user` **já aceitava Bearer** como fallback "(mobile/API)".
O que faltava era o token chegar ao cliente: `login`/`register`/`refresh`
setavam o cookie e devolviam só `{"user": ...}`. A mudança foi devolver os
tokens **também no corpo, e apenas quando o cliente manda o header
`X-Client-Platform: android|ios`**. Sem o header — ou seja, para o site —
a resposta continua idêntica. Coberto por
`website/backend/tests/test_auth_mobile_2026_08.py`.

A sessão única do backend continua valendo: login em outro aparelho derruba
esta, o app detecta o `SESSION_INVALIDATED|` e volta para a tela de login
explicando o motivo.

## Ao vivo

Atualiza a cada 20s, **só** com a tela em foco e o app em primeiro plano
(`src/hooks/useDados.ts`). Em segundo plano o polling para e, ao voltar,
atualiza na hora. A atualização é silenciosa: a lista não pisca nem volta ao
topo enquanto o usuário lê.

## Deep links

O scheme `pickia://` e o App Link de `pickia.com.br` já estão declarados em
`app.json`, e a rota `app/pick/[id].tsx` responde por eles:

```
pickia://pick/123?tipo=vip
pickia://pick/456?tipo=live
```

Testar com o app rodando:

```bash
npx uri-scheme open "pickia://pick/123?tipo=vip" --android
```

Universal Links no iOS e a verificação do App Link no Android precisam do
`assetlinks.json` / `apple-app-site-association` publicados com o
fingerprint do certificado — isso é etapa de loja, fora desta fase.

## Push

Infraestrutura pronta (`src/push/registro.ts`: permissão, canal Android,
token do aparelho). O envio **não** está ligado, de propósito:
`POST /api/notifications/subscribe` grava uma inscrição *Web Push*
(`endpoint` + chaves `p256dh`/`auth` do Service Worker), formato que um app
nativo não produz. Mandar um token Expo/FCM para lá corromperia a tabela que
hoje entrega as notificações do site.

Falta, quando essa fase chegar: coluna/rota para token nativo e envio via FCM
ao lado do webpush atual, em `routers/notifications.py`.

## Lojas

Nada é publicado nesta fase. O que já está preparado em `app.json`:

- `br.com.pickia.app` como applicationId (Android) e bundleIdentifier (iOS) —
  o mesmo id do TWA em `website/android-twa/`, então os dois **não** podem ir
  para a Play Store ao mesmo tempo; este app substitui aquele quando a
  publicação acontecer.
- `versionCode` 1, ícone, splash e cor de tema.
- `associatedDomains` e `intentFilters` para os links.

Ainda faltam para publicar: conta Play Console, EAS project id, screenshots,
e a revisão da política de "Gambling and Contests" da Play Store — que é o
ponto mais provável de rejeição, já anotado em
`website/android-twa/README.md`.
