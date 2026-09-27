import { useCallback, useEffect, useState } from 'react'
import { History, Plus, TrendingDown, TrendingUp, Minus } from 'lucide-react'
import api from '../services/api'
import { Button, Spinner } from './ui'

/*
 * Cada mudança do motor com o resultado de cada produto antes e depois dela.
 *
 * Pedido do usuário: registrar toda mudança e saber como ficou depois. A regra
 * do projeto é não mexer no que funciona; esta tela é o que mostra se a última
 * mexida melhorou ou piorou. Amostra pequena aparece com o número de apostas
 * ao lado, para ninguém decidir em cima de cinco jogos.
 */

interface Janela {
  apostas: number
  acerto: number | null
  lucro: number
  lucro_por_aposta: number
}

interface ProdutoResultado {
  tabela: string
  produto: string
  antes: Janela | null
  depois: Janela | null
}

interface Mudanca {
  id: number
  dia: string
  titulo: string
  descricao: string | null
  dias_depois: number
  produtos_resultado: ProdutoResultado[]
}

const PRODUTOS: { tabela: string; nome: string }[] = [
  { tabela: 'picks_vip', nome: 'Premium' },
  { tabela: 'picks_free', nome: 'Dica do Dia' },
  { tabela: 'picks_multiplas', nome: 'Múltipla' },
  { tabela: 'picks_bingo', nome: 'Bingo' },
  { tabela: 'picks_alavancagem', nome: 'Alavancagem' },
  { tabela: 'picks_boost', nome: 'Pick Boost' },
  { tabela: 'picks_faltas', nome: 'Pick Falta' },
  { tabela: 'picks_player_stats', nome: 'Pick Jogador' },
  { tabela: 'picks_live', nome: 'Ao Vivo' },
]

//: Abaixo disto o antes x depois é sinal, não decisão.
const AMOSTRA_MINIMA = 25

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? '-' : `${(v * 100).toFixed(1).replace('.', ',')}%`
}

function u(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  const s = v.toFixed(2).replace('.', ',')
  return v > 0 ? `+${s}u` : `${s}u`
}

function dataBr(iso: string): string {
  const [a, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${a}`
}

function Tendencia({ antes, depois }: { antes: Janela | null; depois: Janela | null }) {
  if (!antes || !depois) return <Minus size={14} className="text-ink-3" aria-hidden />
  const delta = depois.lucro_por_aposta - antes.lucro_por_aposta
  if (Math.abs(delta) < 0.02) return <Minus size={14} className="text-ink-3" aria-label="igual" />
  return delta > 0
    ? <TrendingUp size={14} className="text-accent-ink" aria-label="melhorou" />
    : <TrendingDown size={14} className="text-red-400" aria-label="piorou" />
}

export default function AdminMudancas() {
  const [dados, setDados] = useState<Mudanca[]>([])
  const [janela, setJanela] = useState(14)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')
  const [abrirForm, setAbrirForm] = useState(false)
  const [form, setForm] = useState({ dia: '', titulo: '', descricao: '', produtos: [] as string[] })
  const [salvando, setSalvando] = useState(false)

  const buscar = useCallback(async () => {
    setCarregando(true)
    setErro('')
    try {
      const { data } = await api.get('/admin/motor/mudancas', { params: { janela } })
      setDados(Array.isArray(data?.mudancas) ? data.mudancas : [])
    } catch {
      setErro('Não foi possível carregar as mudanças agora.')
    } finally {
      setCarregando(false)
    }
  }, [janela])

  useEffect(() => { buscar() }, [buscar])

  const salvar = async () => {
    setSalvando(true)
    setErro('')
    try {
      await api.post('/admin/motor/mudancas', {
        dia: form.dia, titulo: form.titulo,
        descricao: form.descricao || null,
        produtos: form.produtos.length ? form.produtos : null,
      })
      setForm({ dia: '', titulo: '', descricao: '', produtos: [] })
      setAbrirForm(false)
      buscar()
    } catch {
      setErro('Não foi possível registrar a mudança. Confira a data e o título.')
    } finally {
      setSalvando(false)
    }
  }

  const alternarProduto = (tabela: string) => setForm(f => ({
    ...f,
    produtos: f.produtos.includes(tabela)
      ? f.produtos.filter(p => p !== tabela) : [...f.produtos, tabela],
  }))

  return (
    <section className="rounded-md border border-line bg-surface-1 p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm sm:text-base font-semibold text-ink-1">
          <History size={16} aria-hidden />
          Mudanças do motor: antes e depois
        </h2>
        <div className="flex items-center gap-2">
          <select
            value={janela}
            onChange={e => setJanela(Number(e.target.value))}
            className="rounded-md border border-line bg-surface-0 px-2 py-1 text-xs text-ink-1"
            aria-label="Dias de cada lado"
          >
            <option value={7}>7 dias</option>
            <option value={14}>14 dias</option>
            <option value={30}>30 dias</option>
          </select>
          <Button size="sm" Icon={Plus} onClick={() => setAbrirForm(v => !v)}>Registrar</Button>
        </div>
      </div>
      <p className="mt-1 text-xs text-ink-3">
        Compara os {janela} dias antes com os dias depois de cada mudança. Mudanças no mesmo dia
        dividem o mesmo resultado. Com menos de {AMOSTRA_MINIMA} apostas, é sinal para acompanhar, não
        para decidir.
      </p>

      {abrirForm && (
        <div className="mt-3 space-y-2 rounded-md border border-line bg-surface-0 p-3">
          <div className="flex flex-col gap-2 sm:flex-row">
            <input type="date" value={form.dia} onChange={e => setForm(f => ({ ...f, dia: e.target.value }))}
              className="rounded-md border border-line bg-surface-1 px-2 py-1.5 text-sm text-ink-1" aria-label="Data" />
            <input type="text" value={form.titulo} placeholder="O que mudou"
              onChange={e => setForm(f => ({ ...f, titulo: e.target.value }))}
              className="flex-1 rounded-md border border-line bg-surface-1 px-2 py-1.5 text-sm text-ink-1" />
          </div>
          <textarea value={form.descricao} placeholder="Por que mudou (opcional)" rows={2}
            onChange={e => setForm(f => ({ ...f, descricao: e.target.value }))}
            className="w-full rounded-md border border-line bg-surface-1 px-2 py-1.5 text-sm text-ink-1" />
          <div className="flex flex-wrap gap-2">
            {PRODUTOS.map(p => (
              <button key={p.tabela} type="button" onClick={() => alternarProduto(p.tabela)}
                className={`rounded-full border px-2 py-0.5 text-xs ${form.produtos.includes(p.tabela)
                  ? 'border-accent text-accent-ink' : 'border-line text-ink-3'}`}>
                {p.nome}
              </button>
            ))}
          </div>
          <p className="text-xs text-ink-3">Sem produto marcado, vale para todos.</p>
          <Button size="sm" onClick={salvar} disabled={salvando || !form.dia || !form.titulo.trim()}>
            {salvando ? 'Salvando' : 'Salvar mudança'}
          </Button>
        </div>
      )}

      {carregando ? (
        <div className="py-6 flex justify-center"><Spinner /></div>
      ) : erro ? (
        <p className="mt-3 text-sm text-ink-3">{erro}</p>
      ) : dados.length === 0 ? (
        <p className="mt-3 text-sm text-ink-3">Nenhuma mudança registrada ainda.</p>
      ) : (
        <ul className="mt-3 space-y-4">
          {dados.map(m => (
            <li key={m.id} className="border-t border-line pt-3">
              <div className="text-xs text-ink-3">
                {dataBr(m.dia)}{m.dias_depois < janela ? `, ${m.dias_depois} dia${m.dias_depois === 1 ? '' : 's'} depois até hoje` : ''}
              </div>
              <div className="text-sm font-semibold text-ink-1">{m.titulo}</div>
              {m.descricao && <div className="text-xs text-ink-2">{m.descricao}</div>}
              {m.produtos_resultado.length === 0 ? (
                <p className="mt-1 text-xs text-ink-3">Sem apostas liquidadas nas janelas.</p>
              ) : (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-ink-3">
                        <th className="py-1 pr-2 text-left font-normal">Produto</th>
                        <th className="py-1 px-1 text-right font-normal">Antes</th>
                        <th className="py-1 px-1 text-right font-normal">Depois</th>
                        <th className="py-1 pl-1" />
                      </tr>
                    </thead>
                    <tbody>
                      {m.produtos_resultado.map(p => (
                        <tr key={p.tabela} className="text-ink-2">
                          <td className="py-1 pr-2 text-ink-1">{p.produto}</td>
                          <td className="py-1 px-1 text-right whitespace-nowrap">
                            {p.antes ? `${pct(p.antes.acerto)}, ${u(p.antes.lucro_por_aposta)} (${p.antes.apostas})` : '-'}
                          </td>
                          <td className="py-1 px-1 text-right whitespace-nowrap">
                            {p.depois ? `${pct(p.depois.acerto)}, ${u(p.depois.lucro_por_aposta)} (${p.depois.apostas})` : '-'}
                          </td>
                          <td className="py-1 pl-1"><Tendencia antes={p.antes} depois={p.depois} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-1 text-[11px] text-ink-3">Acerto, lucro por aposta e, entre parênteses, quantas apostas.</p>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
