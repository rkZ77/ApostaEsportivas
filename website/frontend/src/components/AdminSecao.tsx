import { useEffect, useState } from 'react'
import { ChevronDown, HelpCircle, X } from 'lucide-react'

/*
 * As duas peças que organizam o /admin.
 *
 * O PROBLEMA QUE ELAS RESOLVEM. Cada aba era uma coluna de painéis empilhados,
 * todos abertos, com título técnico ("Auditoria de resultados", "Eventos de
 * pagamento"). Quem abria a aba via uma parede, sem saber para que ela servia
 * nem por onde começar, e rolava procurando o painel certo.
 *
 * Secao      um painel recolhível. O título é a PERGUNTA que ele responde, em
 *            português de quem opera ("Os resultados do mês estão certos?"); o
 *            nome técnico vai pequeno ao lado, porque é por ele que o código e
 *            as conversas se referem ao painel. Fechado, o conteúdo nem monta:
 *            painel recolhido não faz requisição, o que deixa a aba leve.
 *
 * GuiaDaAba  o topo de cada aba: para que ela serve, quando usar, e um índice
 *            clicável que abre e rola até a seção. Dá pra esconder depois de
 *            aprender, e a escolha fica lembrada.
 *
 * O estado aberto/fechado fica no navegador de quem opera (localStorage), que
 * é conveniência por pessoa e não dado do sistema. Leitura e escrita vão em
 * try/catch: em janela anônima o storage pode não existir, e a tela tem que
 * funcionar igual, só sem lembrar.
 */

/*
 * Ação pequena do admin: "ver log", "por quê", "limpar filtro", "abrir tudo".
 *
 * Eram texto sublinhado, e no meio de texto explicativo sublinhado não se
 * distingue de link nem de ênfase · quem opera não sabia onde dava pra
 * clicar. Ação tem cara de botão: borda e fundo que acende.
 */
export const BOTAO_PEQUENO =
  'inline-flex items-center justify-center gap-1 text-[11px] font-semibold px-2.5 py-1 min-h-[28px] ' +
  'rounded-md border border-line-strong text-ink-2 hover:text-ink-1 hover:border-ink-4 hover:bg-surface-2 ' +
  'transition-colors touch-manipulation disabled:opacity-40 disabled:pointer-events-none'

const CHAVE = (id: string) => `admin.secao.${id}`
const EVENTO_ABRIR = 'admin:abrir-secao'
const EVENTO_TODAS = 'admin:todas-secoes'

function ler(chave: string): string | null {
  try { return window.localStorage.getItem(chave) } catch { return null }
}
function gravar(chave: string, valor: string) {
  try { window.localStorage.setItem(chave, valor) } catch { /* sem storage, só não lembra */ }
}

/** Abre uma seção de fora dela (índice do guia, botão "Editar" de outra seção) e rola até ela. */
export function abrirSecao(id: string) {
  window.dispatchEvent(new CustomEvent(EVENTO_ABRIR, { detail: id }))
  // Espera o conteúdo montar antes de rolar, senão a rolagem para no cabeçalho
  // e o painel cresce para baixo dele.
  window.setTimeout(() => {
    document.getElementById(`secao-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 60)
}

interface SecaoProps {
  id: string
  /** A pergunta que o painel responde, em português simples. */
  titulo: string
  /** Uma frase: o que tem aqui dentro e quando olhar. */
  oQueE: string
  /** Nome técnico do painel, para quem procura pelo nome antigo. */
  tecnico?: string
  abertaPorPadrao?: boolean
  children: React.ReactNode
}

export function Secao({ id, titulo, oQueE, tecnico, abertaPorPadrao = false, children }: SecaoProps) {
  const [aberta, setAberta] = useState(() => {
    const salvo = ler(CHAVE(id))
    return salvo === null ? abertaPorPadrao : salvo === '1'
  })

  const mudar = (valor: boolean) => {
    setAberta(valor)
    gravar(CHAVE(id), valor ? '1' : '0')
  }

  useEffect(() => {
    const abrir = (e: Event) => { if ((e as CustomEvent).detail === id) mudar(true) }
    const todas = (e: Event) => mudar(Boolean((e as CustomEvent).detail))
    window.addEventListener(EVENTO_ABRIR, abrir)
    window.addEventListener(EVENTO_TODAS, todas)
    return () => {
      window.removeEventListener(EVENTO_ABRIR, abrir)
      window.removeEventListener(EVENTO_TODAS, todas)
    }
    // `mudar` só fecha sobre `id`, que é o que a dependência já cobre.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  return (
    <section id={`secao-${id}`} className="mb-3 scroll-mt-4">
      <button
        type="button"
        onClick={() => mudar(!aberta)}
        aria-expanded={aberta}
        className={`w-full text-left flex items-start gap-3 px-4 py-3 rounded-lg border transition-colors touch-manipulation ${
          aberta
            ? 'border-line-strong bg-surface-1'
            : 'border-line bg-surface-1/60 hover:border-line-strong hover:bg-surface-1'}`}
      >
        <ChevronDown
          className={`w-4 h-4 mt-0.5 shrink-0 text-ink-3 transition-transform ${aberta ? '' : '-rotate-90'}`}
          aria-hidden
        />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2 flex-wrap">
            <span className="text-sm font-semibold text-ink-1">{titulo}</span>
            {tecnico && <span className="text-[10px] text-ink-4 font-mono">{tecnico}</span>}
          </span>
          <span className="block text-[11px] text-ink-3 mt-0.5 leading-relaxed">{oQueE}</span>
        </span>
      </button>
      {aberta && <div className="mt-2">{children}</div>}
    </section>
  )
}

interface GuiaProps {
  aba: string
  /** Uma ou duas frases: para que a aba existe. */
  paraQue: string
  /** Situações concretas em que vale abrir a aba. */
  quando?: string[]
  secoes?: { id: string; titulo: string }[]
}

export function GuiaDaAba({ aba, paraQue, quando = [], secoes = [] }: GuiaProps) {
  const chave = `admin.guia.${aba}`
  const [escondido, setEscondido] = useState(() => ler(chave) === '1')

  // Trocar de aba remonta o guia com outra chave · o estado tem que acompanhar.
  useEffect(() => { setEscondido(ler(chave) === '1') }, [chave])

  const mudar = (valor: boolean) => {
    setEscondido(valor)
    gravar(chave, valor ? '1' : '0')
  }

  const indice = secoes.length > 1 && (
    <div className="flex flex-wrap items-center gap-1.5">
      {secoes.map(s => (
        <button key={s.id} type="button" onClick={() => abrirSecao(s.id)}
          className="text-[11px] px-2.5 py-1 rounded-md border border-line text-ink-2 hover:text-ink-1 hover:border-line-strong transition-colors touch-manipulation">
          {s.titulo}
        </button>
      ))}
      <span className="flex gap-1.5 ml-auto pl-2">
        <button type="button" onClick={() => window.dispatchEvent(new CustomEvent(EVENTO_TODAS, { detail: true }))}
          className={BOTAO_PEQUENO}>Abrir tudo</button>
        <button type="button" onClick={() => window.dispatchEvent(new CustomEvent(EVENTO_TODAS, { detail: false }))}
          className={BOTAO_PEQUENO}>Fechar tudo</button>
      </span>
    </div>
  )

  if (escondido) {
    return (
      <div className="mb-4 flex items-start gap-2">
        <div className="flex-1 min-w-0">{indice}</div>
        <button type="button" onClick={() => mudar(false)}
          className={`${BOTAO_PEQUENO} shrink-0`}
          aria-label="Mostrar explicação da aba">
          <HelpCircle className="w-3.5 h-3.5" /> Para que serve
        </button>
      </div>
    )
  }

  return (
    <div className="mb-4 rounded-lg border border-accent/25 bg-accent/[0.05] px-4 py-3">
      <div className="flex items-start gap-3">
        <HelpCircle className="w-4 h-4 text-accent-ink shrink-0 mt-0.5" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-ink-1 leading-relaxed">{paraQue}</p>
          {quando.length > 0 && (
            <>
              <p className="text-[11px] text-ink-3 font-semibold mt-2">Abra esta aba quando:</p>
              <ul className="mt-1 space-y-0.5">
                {quando.map(q => (
                  <li key={q} className="text-[11px] text-ink-2 leading-relaxed flex gap-1.5">
                    <span className="text-ink-4">•</span><span>{q}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <button type="button" onClick={() => mudar(true)}
          className="shrink-0 text-ink-4 hover:text-ink-1" aria-label="Esconder explicação">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      {indice && <div className="mt-3 pt-3 border-t border-accent/15">{indice}</div>}
    </div>
  )
}
