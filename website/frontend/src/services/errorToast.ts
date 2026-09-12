// Canal global e leve para avisar o usuário de falhas de rede que, hoje,
// vários `.catch(() => {})` espalhados pelo app engolem em silêncio.
//
// O `codigo` é o `request_id` que o backend devolve em `X-Request-Id` (ver
// main.py::identidade_da_requisicao). Ele não é mensagem: aparece em letra
// miúda embaixo do aviso, e existe pra pessoa conseguir dizer QUAL erro ela
// viu. Sem ele, "deu erro às 21h" é tudo que chega até nós.
type Listener = (msg: string, codigo?: string) => void
const listeners = new Set<Listener>()

export function notifyError(msg: string, codigo?: string) {
  listeners.forEach(l => l(msg, codigo))
}

export function subscribeError(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
