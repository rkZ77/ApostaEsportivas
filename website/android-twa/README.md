# Pick IA — App Android (TWA)

O app é um **TWA (Trusted Web Activity)**: um wrapper Android fino que abre o
próprio site (`https://pickia.com.br`) em tela cheia, sem barra de navegador.
Não é um app separado para manter — qualquer mudança no site aparece no app
automaticamente. As notificações push que os picks já disparam
(`website/backend/routers/notifications.py` + `website/frontend/public/sw.js`)
funcionam dentro do app sem nenhum código novo, porque o TWA usa o mesmo
Service Worker e a mesma assinatura VAPID do site.

Esse diretório guarda só a config (`twa-manifest.json`). O projeto Android
completo (`app/`, keystore, `.aab`) é gerado localmente e **não deve ser
commitado** (já está no `.gitignore` do repo).

## Pré-requisitos (na sua máquina, não neste ambiente)

- Node.js
- JDK 17
- Android SDK (o Bubblewrap baixa um Android Studio "headless" sozinho no
  primeiro uso, se você não tiver o Android Studio instalado)

## 1. Gerar o projeto e o keystore

```bash
cd website/android-twa
npx @bubblewrap/cli init --manifest https://pickia.com.br/manifest.json
```

O wizard faz perguntas (nome, package id, cores...). Responda com os mesmos
valores já definidos em `twa-manifest.json` deste diretório (package id
`br.com.pickia.app`) ou, se preferir, deixe ele gerar o dele e depois
substitua pelo `twa-manifest.json` daqui antes do build.

Ele vai gerar `android.keystore` com uma senha que **você escolhe e precisa
guardar num gerenciador de senhas**. Se perder esse keystore, não dá pra
publicar atualizações do mesmo app na Play Store nunca mais — só criando um
app novo do zero.

## 2. Build

```bash
npx @bubblewrap/cli build
```

Gera `app-release-signed.aab` e imprime o **SHA256 do certificado** no
terminal.

## 3. Verificação do domínio (Digital Asset Links)

Copie o SHA256 impresso no passo anterior e cole em
[`website/frontend/public/.well-known/assetlinks.json`](../frontend/public/.well-known/assetlinks.json)
no lugar de `REPLACE_WITH_SHA256_FINGERPRINT_AFTER_GENERATING_KEYSTORE`.
Faça commit, deploy (push pra `dev`, depois `main`) e confirme que
`https://pickia.com.br/.well-known/assetlinks.json` abre no navegador com o
fingerprint certo. Sem isso, o app abre com barra de URL do Chrome em vez de
tela cheia.

## 4. Testar antes de publicar

Com um celular Android em modo desenvolvedor (USB debugging) ou emulador:

```bash
npx @bubblewrap/cli install
```

Confirme que abre em tela cheia (sem barra de endereço) — isso confirma que
o Digital Asset Link foi validado — e que uma notificação de teste de picks
aparece normalmente.

## 5. Play Console (a parte que só você pode fazer)

1. Criar conta em [play.google.com/console](https://play.google.com/console)
   — taxa única de US$25, exige verificação de identidade (pode levar alguns
   dias).
2. Criar o app, preencher ficha da loja: nome, descrições, categoria
   (Esportes), ícone 512×512, screenshots do site em formato mobile.
3. Política de privacidade: já existe em `https://pickia.com.br/privacidade`
   — usar essa URL no formulário.
4. **Atenção**: como o app dá picks/dicas de apostas esportivas, ele pode
   cair na política de "Gambling and Contests" da Play Store mesmo sem
   apostar dinheiro dentro do app. Revisar essa política antes de submeter —
   pode exigir classificação 18+, restrição de país ou declaração extra no
   formulário de Data Safety. Vale ler a política oficial antes de mandar
   pra revisão pra não tomar rejeição.
5. Fazer upload do `app-release-signed.aab` gerado no passo 2 e enviar pra
   revisão.

## Atualizações futuras

Mudança de conteúdo/frontend do site: nada a fazer, aparece sozinho no app.
Só precisa gerar novo build e reenviar pra Play Store se mudar nome, ícone,
cor do tema, ou algo em `twa-manifest.json` — nesse caso, suba
`appVersionCode` em 1 antes de rodar `bubblewrap build` de novo.
