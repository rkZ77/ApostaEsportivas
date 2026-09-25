/**
 * Verificação anti-bot do login e do cadastro · espelho nativo de
 * `website/frontend/src/components/Turnstile.tsx`.
 *
 * Por que existe: em produção o backend exige `captcha_token` em
 * `/auth/login` e `/auth/register` (`_verify_captcha` em routers/auth.py).
 * Sem isto o app recebe 400 e ninguém entra. Pular a checagem por header no
 * backend não serve: qualquer robô manda o header, e a proteção do site
 * cairia junto.
 *
 * Como funciona: o widget do Cloudflare roda numa WebView pequena carregada
 * com `baseUrl` do site, porque a chave só vale no domínio cadastrado. O token
 * volta por `postMessage`. Ele é de uso único: depois de cada tentativa a tela
 * chama `reiniciar()` para pegar outro, como o site faz com `reset()`.
 *
 * Sem `EXPO_PUBLIC_TURNSTILE_SITE_KEY` (DEV), não desenha nada e o token fica
 * vazio · o backend de DEV também não tem a chave secreta e pula a checagem.
 */
import { forwardRef, useImperativeHandle, useState } from 'react'
import { View } from 'react-native'
import { WebView, type WebViewMessageEvent } from 'react-native-webview'
import { SITE_URL, TURNSTILE_SITE_KEY } from '../config/env'
import { cores } from '../theme/tokens'

export interface CaptchaHandle {
  reiniciar: () => void
}

function pagina(chave: string): string {
  // JSON.stringify escapa a chave para dentro do script.
  return `<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=iniciar" async defer></script>
<style>html,body{margin:0;background:${cores.surface0};display:flex;justify-content:center}</style>
</head><body><div id="w"></div><script>
function enviar(t){window.ReactNativeWebView.postMessage(t||'')}
function iniciar(){turnstile.render('#w',{sitekey:${JSON.stringify(chave)},theme:'dark',
callback:enviar,'expired-callback':function(){enviar('')},'error-callback':function(){enviar('')}})}
</script></body></html>`
}

export const Captcha = forwardRef<CaptchaHandle, { aoVerificar: (token: string) => void }>(
  ({ aoVerificar }, ref) => {
    // Trocar a key remonta a WebView, que renderiza um widget novo.
    const [geracao, setGeracao] = useState(0)

    useImperativeHandle(ref, () => ({
      reiniciar: () => {
        aoVerificar('')
        setGeracao((g) => g + 1)
      },
    }))

    if (!TURNSTILE_SITE_KEY) return null

    return (
      <View style={{ height: 70, overflow: 'hidden' }}>
        <WebView
          key={geracao}
          source={{ html: pagina(TURNSTILE_SITE_KEY), baseUrl: SITE_URL }}
          onMessage={(e: WebViewMessageEvent) => aoVerificar(e.nativeEvent.data)}
          style={{ backgroundColor: cores.surface0 }}
          scrollEnabled={false}
          javaScriptEnabled
          originWhitelist={['*']}
        />
      </View>
    )
  },
)
Captcha.displayName = 'Captcha'

/** Sem chave o backend não exige token · o botão não deve esperar por ele. */
export const CAPTCHA_ATIVO = Boolean(TURNSTILE_SITE_KEY)
