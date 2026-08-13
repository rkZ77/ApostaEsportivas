/**
 * Carregamento de dados com os três estados que toda tela do app precisa:
 * carregando, erro e conteúdo · mais "puxar para atualizar".
 *
 * Sobre polling (§12): quem passa `intervaloMs` só continua atualizando
 * enquanto a tela está em foco E o app está em primeiro plano. App em
 * segundo plano não gasta bateria nem cota de rede batendo numa API que o
 * usuário não está olhando -- e ao voltar, atualiza na hora, então a tela
 * nunca mostra dado velho sem o usuário perceber.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { AppState } from 'react-native'
import { useFocusEffect } from 'expo-router'
import { mensagemDeErro } from '../api/client'

interface Opcoes {
  /** Milissegundos entre atualizações automáticas. Sem isso, carrega uma vez só. */
  intervaloMs?: number
  /** Deixa de buscar enquanto for false (ex.: esperando a sessão carregar). */
  habilitado?: boolean
}

export function useDados<T>(buscar: () => Promise<T>, deps: unknown[] = [], opcoes: Opcoes = {}) {
  const { intervaloMs, habilitado = true } = opcoes

  const [dados, setDados] = useState<T | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [atualizando, setAtualizando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  /* A função de busca muda de identidade a cada render; guardá-la numa ref
     evita reinstalar o intervalo a cada frame. */
  const buscarRef = useRef(buscar)
  buscarRef.current = buscar

  const montado = useRef(true)
  useEffect(() => {
    montado.current = true
    return () => {
      montado.current = false
    }
  }, [])

  const executar = useCallback(async (silencioso: boolean) => {
    // Desabilitado não é "carregando para sempre": a tela precisa poder
    // desenhar seu estado alternativo (paywall, sessão ainda carregando).
    if (!habilitado) {
      setCarregando(false)
      setAtualizando(false)
      return
    }
    if (!silencioso) setCarregando(true)
    try {
      const resultado = await buscarRef.current()
      if (!montado.current) return
      setDados(resultado)
      setErro(null)
    } catch (e) {
      if (!montado.current) return
      // Numa atualização silenciosa mantemos o que já está na tela: piscar um
      // erro por causa de uma falha de rede passageira é pior que o dado
      // ficar alguns segundos velho.
      if (!silencioso) setErro(mensagemDeErro(e))
    } finally {
      if (montado.current) {
        setCarregando(false)
        setAtualizando(false)
      }
    }
  }, [habilitado])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    void executar(false)
  }, [...deps, habilitado])

  /* Polling preso ao foco da tela e ao estado do app. */
  useFocusEffect(
    useCallback(() => {
      if (!intervaloMs || !habilitado) return

      let timer: ReturnType<typeof setInterval> | null = null

      const ligar = () => {
        if (timer) return
        timer = setInterval(() => void executar(true), intervaloMs)
      }
      const desligar = () => {
        if (timer) clearInterval(timer)
        timer = null
      }

      ligar()
      const inscricao = AppState.addEventListener('change', (estado) => {
        if (estado === 'active') {
          void executar(true) // volta do segundo plano já atualizando
          ligar()
        } else {
          desligar()
        }
      })

      return () => {
        desligar()
        inscricao.remove()
      }
    }, [intervaloMs, habilitado, executar]),
  )

  const atualizar = useCallback(() => {
    setAtualizando(true)
    void executar(true)
  }, [executar])

  return { dados, carregando, atualizando, erro, atualizar, recarregar: () => executar(false) }
}
