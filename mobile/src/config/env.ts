/**
 * Para onde o app aponta -- e a trava que impede DEV de falar com produção.
 *
 * O backend do Pick IA é um só (`website/backend`, FastAPI em :8000). O que
 * muda entre ambientes é o banco que ele abre, via `DB_ENV`. Então "apontar
 * pro DEV" aqui significa: falar com a instância local que subiu com
 * `DB_ENV=dev`, nunca com `pickia.com.br`.
 *
 * Descoberta automática do host: em vez de exigir que cada máquina edite um
 * IP na mão, a URL padrão sai do próprio Metro. `hostUri` é o endereço em que
 * o bundler está servindo -- no emulador vem `10.0.2.2`, no celular físico
 * vem o IP da LAN da máquina de desenvolvimento, que é exatamente o endereço
 * pelo qual aquele aparelho consegue enxergar o backend. Trocar de aparelho
 * não pede reconfiguração.
 */
import Constants from 'expo-constants'

const PORTA_API_DEV = 8000

/** Domínios que só existem em produção. Bloqueados em build de desenvolvimento. */
const HOSTS_DE_PRODUCAO = ['pickia.com.br', 'www.pickia.com.br']

function hostDoBundler(): string | null {
  // `hostUri` chega como "192.168.0.14:8081" ou "10.0.2.2:8081".
  const uri = Constants.expoConfig?.hostUri ?? null
  if (!uri) return null
  const host = uri.split(':')[0]?.trim()
  return host && host.length > 0 ? host : null
}

function urlPadraoDeDev(): string {
  const host = hostDoBundler() ?? 'localhost'
  return `http://${host}:${PORTA_API_DEV}`
}

function ehProducao(url: string): boolean {
  return HOSTS_DE_PRODUCAO.some((h) => url.includes(h))
}

function resolverBaseUrl(): string {
  const declarada = process.env.EXPO_PUBLIC_API_URL?.trim()

  if (declarada) {
    // A trava do §11: em desenvolvimento, apontar pro domínio de produção é
    // erro de configuração, não preferência. Falhar aqui é barato; descobrir
    // depois que o app de teste escreveu no banco real, não.
    if (__DEV__ && ehProducao(declarada)) {
      throw new Error(
        `[Pick IA] EXPO_PUBLIC_API_URL aponta para produção (${declarada}) em build de desenvolvimento. ` +
          'Use o backend local com DB_ENV=dev ou remova a variável para autodetectar.',
      )
    }
    return declarada.replace(/\/+$/, '')
  }

  return urlPadraoDeDev()
}

export const API_BASE_URL = resolverBaseUrl()

/** Rótulo do ambiente, mostrado no Perfil para não restar dúvida de onde o app está lendo. */
export const AMBIENTE: 'dev' | 'producao' = ehProducao(API_BASE_URL) ? 'producao' : 'dev'

export const NOME_APP = 'Pick IA'

/** Site público · Termos, Privacidade e o gerenciamento da conta moram lá. */
export const SITE_URL = 'https://pickia.com.br'

/*
 * O app oferece plano pago?
 *
 * Desligado nos dois sistemas enquanto não existir compra pela loja. Apple
 * (diretriz 3.1.1/3.1.3) e Google Play (política de Pagamentos) exigem a
 * cobrança da própria loja para liberar conteúdo digital, e proíbem o app de
 * mandar o usuário pagar em outro lugar. Um botão "assine no site" é motivo
 * direto de rejeição. Quem já assinou no site entra e usa normalmente: isso as
 * duas lojas permitem. Ver mobile/docs/AUDITORIA.md §14 e §15.
 */
export const OFERECE_PLANO_NO_APP = false

/** Timeout de rede. Curto o bastante para a tela não ficar pendurada em túnel ruim. */
export const TIMEOUT_MS = 15000
