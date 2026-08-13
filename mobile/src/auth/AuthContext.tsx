/**
 * Sessão do app · espelho nativo de `website/frontend/src/context/AuthContext.tsx`.
 *
 * As regras de plano NÃO são decididas aqui. `isVip` reproduz exatamente a
 * mesma expressão do site (admin sempre; vip/trial enquanto não expirou) só
 * para a UI saber o que desenhar -- o que libera ou bloqueia conteúdo de
 * verdade continua sendo o backend, que responde 403 quando não pode.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { autenticacao } from '../api/endpoints'
import { registrarPerdaDeSessao } from '../api/client'
import { carregarSessao, limparSessao, salvarSessao } from '../api/session'
import type { Usuario } from '../api/types'

interface Contexto {
  usuario: Usuario | null
  carregando: boolean
  /** Motivo pelo qual a sessão caiu, para a tela de login explicar o que houve. */
  sessaoDerrubadaEm: string | null
  entrar: (identificador: string, senha: string) => Promise<Usuario>
  cadastrar: (dados: Parameters<typeof autenticacao.cadastrar>[0]) => Promise<Usuario>
  sair: () => Promise<void>
  recarregarUsuario: () => Promise<void>
  isVip: boolean
  isAdmin: boolean
}

const AuthContext = createContext<Contexto | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [sessaoDerrubadaEm, setSessaoDerrubadaEm] = useState<string | null>(null)

  /* Abertura do app: lê o token do keystore e confirma no servidor quem é o
     usuário. Nunca confiamos num objeto de usuário gravado no aparelho --
     plano pode ter expirado ou sido alterado enquanto o app estava fechado. */
  useEffect(() => {
    let vivo = true
    ;(async () => {
      const { access } = await carregarSessao()
      if (!access) {
        if (vivo) setCarregando(false)
        return
      }
      try {
        const u = await autenticacao.eu()
        if (vivo) setUsuario(u)
      } catch {
        await limparSessao()
      } finally {
        if (vivo) setCarregando(false)
      }
    })()
    return () => {
      vivo = false
    }
  }, [])

  /* O interceptor avisa quando a sessão morreu de vez (refresh falhou ou
     login em outro aparelho derrubou esta). Aqui só limpamos o estado · o
     roteador reage sozinho e manda para o login. */
  useEffect(() => {
    registrarPerdaDeSessao((motivo, dispositivo) => {
      setUsuario(null)
      setSessaoDerrubadaEm(motivo === 'derrubada' ? dispositivo ?? 'outro dispositivo' : null)
    })
    return () => registrarPerdaDeSessao(null)
  }, [])

  const entrar = useCallback(async (identificador: string, senha: string) => {
    const dados = await autenticacao.entrar(identificador, senha)
    if (dados.access_token) await salvarSessao(dados.access_token, dados.refresh_token)
    setUsuario(dados.user)
    setSessaoDerrubadaEm(null)
    return dados.user
  }, [])

  const cadastrar = useCallback(async (dados: Parameters<typeof autenticacao.cadastrar>[0]) => {
    const resposta = await autenticacao.cadastrar(dados)
    if (resposta.access_token) await salvarSessao(resposta.access_token, resposta.refresh_token)
    setUsuario(resposta.user)
    setSessaoDerrubadaEm(null)
    return resposta.user
  }, [])

  const sair = useCallback(async () => {
    // Avisa o servidor para encerrar a sessão do lado de lá; se a rede
    // falhar, ainda assim apagamos a credencial do aparelho.
    try {
      await autenticacao.sair()
    } catch {
      /* segue o fluxo */
    }
    await limparSessao()
    setUsuario(null)
    setSessaoDerrubadaEm(null)
  }, [])

  const recarregarUsuario = useCallback(async () => {
    try {
      setUsuario(await autenticacao.eu())
    } catch {
      /* o interceptor cuida do 401 */
    }
  }, [])

  const valor = useMemo<Contexto>(() => {
    const vipAtivo =
      usuario?.plan === 'admin' ||
      ((usuario?.plan === 'vip' || usuario?.plan === 'trial') &&
        (!usuario.expires_at || new Date(usuario.expires_at) > new Date()))

    return {
      usuario,
      carregando,
      sessaoDerrubadaEm,
      entrar,
      cadastrar,
      sair,
      recarregarUsuario,
      isVip: Boolean(vipAtivo),
      isAdmin: usuario?.plan === 'admin',
    }
  }, [usuario, carregando, sessaoDerrubadaEm, entrar, cadastrar, sair, recarregarUsuario])

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>
}

export function useAuth(): Contexto {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth precisa estar dentro de AuthProvider')
  return ctx
}
