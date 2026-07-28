import { useState } from 'react'

export interface AgentMessage {
  role: 'user' | 'assistant'
  content: string
}

/** Lógica compartilhada do chat com o Agente IA (streaming via /api/chat) ·
 * usada pela página cheia /agente e pelo widget flutuante. */
export function useAgentChat() {
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [statusText, setStatusText] = useState('')

  const sendMessage = async (text?: string) => {
    const content = (text ?? input).trim()
    if (!content || loading) return

    const userMsg: AgentMessage = { role: 'user', content }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInput('')
    setLoading(true)
    setStatusText('')

    // Adiciona mensagem assistente vazia (mostrará loading)
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ messages: newMessages }),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err.detail ?? 'Erro na resposta do servidor')
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue

          let event: any
          try { event = JSON.parse(raw) } catch { continue }

          if (event.type === 'status') {
            setStatusText(event.text)
          } else if (event.type === 'chunk') {
            if (event.first) setStatusText('')
            setMessages(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = {
                ...updated[updated.length - 1],
                content: updated[updated.length - 1].content + event.text,
              }
              return updated
            })
          } else if (event.type === 'done') {
            break
          }
        }
      }
    } catch (err: any) {
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `Erro: ${err.message ?? 'Falha na conexão'}`,
        }
        return updated
      })
    } finally {
      setLoading(false)
      setStatusText('')
    }
  }

  return { messages, input, setInput, loading, statusText, sendMessage }
}
