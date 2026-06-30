// Canal global e leve para avisar o usuário de falhas de rede que, hoje,
// vários `.catch(() => {})` espalhados pelo app engolem em silêncio.
type Listener = (msg: string) => void
const listeners = new Set<Listener>()

export function notifyError(msg: string) {
  listeners.forEach(l => l(msg))
}

export function subscribeError(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
