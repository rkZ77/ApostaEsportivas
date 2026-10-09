import { useMemo, useState, type RefObject } from 'react'
import { AlertTriangle, CheckCircle2, Copy, Search, XCircle } from 'lucide-react'

/*
 * Log ao vivo do pipeline (09/10/2026, pedido do usuário: "melhora esse
 * formato de log").
 *
 * Era a saída crua dos scripts num <pre>, só com o vermelho do stderr. Agora
 * cada linha é classificada (etapa, erro, aviso, sucesso, normal), a marca do
 * script ([VIP_ENGINE], [ODDS]...) vira selo, e dá pra filtrar só os
 * problemas, buscar e copiar. O TEXTO não muda: é a mesma linha que o script
 * imprimiu, só desenhada de outro jeito -- o log continua sendo a prova do que
 * rodou.
 */

export type TipoDeLinha = 'etapa' | 'erro' | 'aviso' | 'ok' | 'normal'

export interface LinhaDoLog {
  tipo: TipoDeLinha
  texto: string
  marca?: string
  etapa?: { n: number; total: number }
}

const ERRO = /traceback|exception|error|erro\b|falhou|falha ao|cancelad|excedeu o limite/i
const AVISO = /aviso|warning|pulando|n[aã]o publicad|sem odds|vetad|descartad|adiad|insuficiente/i
const OK = /\bsalv[oa]s?\b|picks? salvos|conclu[ií]d|\bok\b|✅|gravad[oa]/i

/** Classifica uma linha crua do log. Pura -- é o que o teste cobre. */
export function classificarLinha(bruta: string): LinhaDoLog {
  const etapa = /^─+\s*\[(\d+)\/(\d+)\]\s*(.+?)\s*─*$/.exec(bruta)
  if (etapa) {
    return { tipo: 'etapa', texto: etapa[3], etapa: { n: Number(etapa[1]), total: Number(etapa[2]) } }
  }
  const stderr = bruta.startsWith('! ')
  let texto = stderr ? bruta.slice(2) : bruta
  let marca: string | undefined
  const m = /^\s*\[([A-Za-z0-9_/ .-]{2,30})\]\s*/.exec(texto)
  if (m) {
    marca = m[1]
    texto = texto.slice(m[0].length)
  }
  const tipo: TipoDeLinha = ERRO.test(texto) ? 'erro'
    : AVISO.test(texto) ? 'aviso'
    : stderr ? 'aviso'
    : OK.test(texto) ? 'ok'
    : 'normal'
  return { tipo, texto, marca }
}

const CORES_DE_MARCA = [
  'text-sky-300 bg-sky-500/10 border-sky-500/25',
  'text-violet-300 bg-violet-500/10 border-violet-500/25',
  'text-teal-300 bg-teal-500/10 border-teal-500/25',
  'text-amber-300 bg-amber-500/10 border-amber-500/25',
  'text-pink-300 bg-pink-500/10 border-pink-500/25',
  'text-lime-300 bg-lime-500/10 border-lime-500/25',
]

/** A mesma marca sempre com a mesma cor, em qualquer rodada. */
export function corDaMarca(marca: string): string {
  let h = 0
  for (const c of marca) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return CORES_DE_MARCA[h % CORES_DE_MARCA.length]
}

const COR_DO_TEXTO: Record<TipoDeLinha, string> = {
  etapa: 'text-ink-1', erro: 'text-red-400', aviso: 'text-orange-300',
  ok: 'text-green-400', normal: 'text-ink-2',
}

interface Props {
  titulo: string
  rodando: boolean
  linhas: string[]
  seguir: boolean
  onSeguir: (v: boolean) => void
  onFechar: () => void
  fimRef: RefObject<HTMLDivElement>
}

export default function LogAoVivo({ titulo, rodando, linhas, seguir, onSeguir, onFechar, fimRef }: Props) {
  const [filtro, setFiltro] = useState<'tudo' | 'problemas'>('tudo')
  const [busca, setBusca] = useState('')
  const [copiado, setCopiado] = useState(false)

  const classificadas = useMemo(() => linhas.map(classificarLinha), [linhas])
  const contagem = useMemo(() => ({
    erros: classificadas.filter(l => l.tipo === 'erro').length,
    avisos: classificadas.filter(l => l.tipo === 'aviso').length,
  }), [classificadas])
  const visiveis = classificadas.filter(l => {
    if (filtro === 'problemas' && l.tipo !== 'erro' && l.tipo !== 'aviso' && l.tipo !== 'etapa') return false
    if (busca && l.tipo !== 'etapa'
        && !`${l.marca ?? ''} ${l.texto}`.toLowerCase().includes(busca.toLowerCase())) return false
    return true
  })

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(linhas.join('\n'))
      setCopiado(true)
      setTimeout(() => setCopiado(false), 1500)
    } catch { /* sem permissão de área de transferência: nada a fazer */ }
  }

  const botao = (ativo: boolean) =>
    `text-[10px] px-2 py-0.5 rounded border transition-colors ${
      ativo ? 'border-accent/50 text-accent-ink bg-accent/10' : 'border-line text-ink-3 hover:text-ink-1'}`

  return (
    <div className="mt-4 border border-line rounded-lg overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 bg-surface-2 border-b border-line">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2 h-2 rounded-full shrink-0 ${rodando ? 'bg-yellow-400 animate-pulse' : 'bg-surface-3'}`} />
          <span className="text-[11px] font-semibold text-ink-1 truncate">{titulo}</span>
          <span className="text-[10px] text-ink-4 shrink-0">{linhas.length} linha(s)</span>
          {contagem.erros > 0 && (
            <span className="text-[10px] text-red-400 flex items-center gap-0.5 shrink-0">
              <XCircle className="w-3 h-3" /> {contagem.erros}
            </span>
          )}
          {contagem.avisos > 0 && (
            <span className="text-[10px] text-orange-300 flex items-center gap-0.5 shrink-0">
              <AlertTriangle className="w-3 h-3" /> {contagem.avisos}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button className={botao(filtro === 'tudo')} onClick={() => setFiltro('tudo')}>Tudo</button>
          <button className={botao(filtro === 'problemas')} onClick={() => setFiltro('problemas')}>
            Só erros e avisos
          </button>
          <label className="flex items-center gap-1 border border-line rounded px-1.5 py-0.5">
            <Search className="w-3 h-3 text-ink-4" />
            <input value={busca} onChange={e => setBusca(e.target.value)} placeholder="buscar"
                   className="bg-transparent text-[10px] text-ink-1 w-20 outline-none placeholder:text-ink-4" />
          </label>
          <label className="text-[10px] text-ink-4 flex items-center gap-1 cursor-pointer">
            <input type="checkbox" checked={seguir} onChange={e => onSeguir(e.target.checked)}
                   className="accent-current w-3 h-3" />
            seguir
          </label>
          <button className={botao(false)} onClick={copiar} title="Copiar o log inteiro">
            <span className="flex items-center gap-1"><Copy className="w-3 h-3" />{copiado ? 'copiado' : 'copiar'}</span>
          </button>
          <button className={botao(false)} onClick={onFechar}>Fechar</button>
        </div>
      </div>

      <div className="bg-surface-0 max-h-96 overflow-y-auto py-1.5 font-mono text-[11px] leading-relaxed">
        {linhas.length === 0 ? (
          <p className="text-[11px] text-ink-4 px-3 py-2 font-sans">
            {rodando ? 'Aguardando a primeira linha…' : 'Sem log. Rode a etapa para acompanhar aqui.'}
          </p>
        ) : visiveis.length === 0 ? (
          <p className="text-[11px] text-ink-4 px-3 py-2 font-sans">Nenhuma linha com esse filtro.</p>
        ) : visiveis.map((l, i) => l.tipo === 'etapa' ? (
          <div key={i} className="flex items-center gap-2 px-3 pt-3 pb-1 font-sans">
            <span className="text-[10px] font-bold text-ink-4 tabular-nums">
              {String(l.etapa!.n).padStart(2, '0')}/{String(l.etapa!.total).padStart(2, '0')}
            </span>
            <span className="text-xs font-semibold text-ink-1">{l.texto}</span>
            <span className="flex-1 h-px bg-line" />
          </div>
        ) : (
          <div key={i} className={`flex items-start gap-2 px-3 py-[1px] ${
            l.tipo === 'erro' ? 'bg-red-500/5' : l.tipo === 'aviso' ? 'bg-orange-500/5' : ''}`}>
            <span className="w-3 shrink-0 pt-[2px]">
              {l.tipo === 'erro' && <XCircle className="w-3 h-3 text-red-400" />}
              {l.tipo === 'aviso' && <AlertTriangle className="w-3 h-3 text-orange-300" />}
              {l.tipo === 'ok' && <CheckCircle2 className="w-3 h-3 text-green-400" />}
            </span>
            {l.marca && (
              <span className={`shrink-0 text-[9px] font-sans font-bold px-1.5 rounded border ${corDaMarca(l.marca)}`}>
                {l.marca}
              </span>
            )}
            <span className={`min-w-0 whitespace-pre-wrap break-words ${COR_DO_TEXTO[l.tipo]}`}>{l.texto}</span>
          </div>
        ))}
        <div ref={fimRef} />
      </div>
    </div>
  )
}
