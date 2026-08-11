/**
 * Onde a sessão do app mora.
 *
 * No site a sessão vive em cookie httpOnly, que o JS nunca enxerga. No
 * nativo não existe equivalente: o token precisa ser guardado por alguém.
 * `expo-secure-store` usa o Keystore no Android e a Keychain no iOS, que é o
 * mais próximo disso -- fica fora do sandbox de arquivos do app e não vai
 * junto num backup comum.
 *
 * O objeto `user` continua saindo do servidor a cada `/auth/me`; o que fica
 * gravado aqui é só credencial.
 */
import * as SecureStore from 'expo-secure-store'

const CHAVE_ACCESS = 'pickia.access_token'
const CHAVE_REFRESH = 'pickia.refresh_token'

/* Cache em memória para o interceptor não pagar um await no Keystore a cada
   requisição. O disco continua sendo a fonte na hora de abrir o app. */
let accessEmMemoria: string | null = null
let refreshEmMemoria: string | null = null

export async function carregarSessao(): Promise<{ access: string | null; refresh: string | null }> {
  try {
    const [access, refresh] = await Promise.all([
      SecureStore.getItemAsync(CHAVE_ACCESS),
      SecureStore.getItemAsync(CHAVE_REFRESH),
    ])
    accessEmMemoria = access
    refreshEmMemoria = refresh
    return { access, refresh }
  } catch {
    // Keystore indisponível (aparelho sem lock screen, por exemplo): o app
    // continua funcionando, só não persiste entre reinícios.
    return { access: accessEmMemoria, refresh: refreshEmMemoria }
  }
}

export async function salvarSessao(access: string, refresh?: string | null): Promise<void> {
  accessEmMemoria = access
  if (refresh) refreshEmMemoria = refresh
  try {
    await SecureStore.setItemAsync(CHAVE_ACCESS, access)
    if (refresh) await SecureStore.setItemAsync(CHAVE_REFRESH, refresh)
  } catch {
    /* mantém só em memória */
  }
}

export async function limparSessao(): Promise<void> {
  accessEmMemoria = null
  refreshEmMemoria = null
  try {
    await Promise.all([
      SecureStore.deleteItemAsync(CHAVE_ACCESS),
      SecureStore.deleteItemAsync(CHAVE_REFRESH),
    ])
  } catch {
    /* já está limpo em memória, que é o que o interceptor lê */
  }
}

export function accessToken(): string | null {
  return accessEmMemoria
}

export function refreshToken(): string | null {
  return refreshEmMemoria
}
