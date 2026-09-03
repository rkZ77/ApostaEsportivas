/*
 * Estatística de jogador que a API não entregou, e o campo pra preencher.
 *
 * POR QUE ESTA TELA LEVA A DIGITAR, E NÃO A "RODAR"
 * -------------------------------------------------
 * A tela irmã (partidas) tem o botão Rodar porque lá a folha costuma chegar
 * atrasada: recoletar resolve. Aqui não. Medido contra a API no fixture
 * 1557377, com os dois goleiros em campo por 90 minutos, ela devolve
 * `"saves": 1` para um e `"saves": null` para o outro. O `null` não é folha
 * atrasada, é dado que a fonte não tem — recoletar traz o mesmo `null`.
 *
 * Por isso o caminho aqui é o campo de digitar, e o que foi digitado fica
 * marcado em `manual_stats` (o quê, por quem, quando). O motor lê a coluna
 * normalmente; a marca existe pra depois dar pra separar o que veio da API do
 * que foi preenchido à mão — sem ela, a média de um goleiro misturaria as duas
 * coisas sem aviso.
 *
 * Arquivo separado de propósito: `AdminDados.tsx` já tem 2.400 linhas e onze
 * endpoints. Somar mais um bloco lá dentro é o que tornou aquela aba difícil
 * de mexer.
 */
import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Check, Pencil, RefreshCw } from 'lucide-react'
import api from '../services/api'
import { Button, EmptyState, ErrorState, Pagination, SkeletonRows } from './ui'

type Familia = {
  chave: string
  rotulo: string
  faltando: number
  elegiveis: number
  pct: number
  so_goleiro: boolean
  usada_pelo_motor: boolean
  /** `null` aqui provavelmente é ZERO, não ausência — a tela não chama de buraco. */
  zero_implicito: boolean
}

type Atuacao = {
  fixture_id: number
  player_id: number
  player_name: string
  team_name: string | null
  position: string | null
  minutes: number | null
  match_date: string
  league_name: string | null
  last_updated: string | null
  manual_stats: Record<string, { valor: number | null; por?: string; em?: string }> | null
}

const dia = (d?: string | null) => (d ? d.slice(8, 10) + '/' + d.slice(5, 7) : '-')

export default function AdminLacunasJogador() {
  const [familias, setFamilias] = useState<Familia[] | null>(null)
  const [familia, setFamilia] = useState('defesas')
  const [lista, setLista] = useState<{ atuacoes: Atuacao[]; total: number; rotulo: string } | null>(null)
  const [pagina, setPagina] = useState(0)
  const [erro, setErro] = useState('')
  const [editando, setEditando] = useState<string | null>(null)
  const [valor, setValor] = useState('')
  const [salvando, setSalvando] = useState(false)

  const buscarFamilias = useCallback(() => {
    api.get('/admin/dados/jogadores/lacunas')
      .then(r => setFamilias(r.data?.familias ?? []))
      .catch(() => setErro('Não deu pra ler as lacunas de jogador.'))
  }, [])

  const buscarLista = useCallback((f: string, p: number) => {
    setLista(null)
    api.get('/admin/dados/jogadores/atuacoes', { params: { familia: f, pagina: p } })
      .then(r => setLista(r.data))
      .catch(() => setErro('Não deu pra ler as atuações.'))
  }, [])

  useEffect(() => { buscarFamilias() }, [buscarFamilias])
  useEffect(() => { buscarLista(familia, pagina) }, [familia, pagina, buscarLista])

  async function salvar(a: Atuacao) {
    setSalvando(true)
    try {
      // Campo vazio grava `null` de propósito: é como se desfaz um número
      // digitado errado sem inventar zero no lugar.
      const v = valor.trim() === '' ? null : Number(valor)
      await api.put(`/admin/dados/jogadores/${a.player_id}/atuacoes/${a.fixture_id}`,
                    { valores: { [familia]: v } })
      setEditando(null)
      setValor('')
      buscarFamilias()
      buscarLista(familia, pagina)
    } catch (e: any) {
      setErro(e?.response?.data?.detail || 'Não deu pra gravar.')
    } finally {
      setSalvando(false)
    }
  }

  if (erro && !familias) return <ErrorState title="Não deu pra ler" description={erro} />

  /* Só o que o motor lê, e só o que tem buraco. As famílias em que `null` quer
     dizer zero (gols, amarelos) ficam fora: mandar alguém digitar 0 em onze mil
     atuações seria trabalho inventado. */
  const acionaveis = (familias ?? []).filter(
    f => f.usada_pelo_motor && !f.zero_implicito && f.faltando > 0)

  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-ink-1">Estatística de jogador que faltou</h3>
          <p className="text-[11px] text-ink-4 mt-0.5 leading-relaxed">
            Aqui recoletar não resolve: a API devolve o mesmo vazio. O caminho é digitar,
            e o que for digitado fica marcado como manual.
          </p>
        </div>
        <button type="button" onClick={() => { buscarFamilias(); buscarLista(familia, pagina) }}
                className="shrink-0 text-ink-4 hover:text-ink-1" aria-label="Atualizar">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {!familias ? (
        <SkeletonRows rows={3} />
      ) : acionaveis.length === 0 ? (
        <EmptyState title="Nada faltando" description="Todas as famílias que o motor lê estão completas." />
      ) : (
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {acionaveis.map(f => (
            <button
              key={f.chave}
              type="button"
              onClick={() => { setFamilia(f.chave); setPagina(0) }}
              className={`shrink-0 text-xs px-3 py-2 rounded-lg border transition-colors ${
                familia === f.chave
                  ? 'border-line-strong bg-surface-2 text-ink-1'
                  : 'border-line text-ink-3 hover:text-ink-2'}`}
            >
              {f.rotulo}
              <span className="ml-1.5 font-mono text-[10px] text-yellow-400">{f.faltando}</span>
            </button>
          ))}
        </div>
      )}

      {!lista ? (
        <SkeletonRows rows={4} />
      ) : lista.atuacoes.length === 0 ? (
        <EmptyState title="Nenhuma atuação" description="Sem lacuna nesta família." />
      ) : (
        <>
          <ul className="divide-y divide-line">
            {lista.atuacoes.map(a => {
              const chave = `${a.player_id}:${a.fixture_id}`
              const jaManual = a.manual_stats?.[familia]
              return (
                <li key={chave} className="py-2.5 flex items-center gap-2 text-xs">
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-ink-1 truncate">
                      {a.player_name}
                      {a.position && <span className="text-ink-4 font-normal"> · {a.position}</span>}
                    </p>
                    <p className="text-[10px] text-ink-4 truncate">
                      {a.team_name} · {dia(a.match_date)} · {a.minutes ?? '-'} min
                      {jaManual && (
                        <span className="text-accent-ink"> · preenchido por {jaManual.por}</span>
                      )}
                    </p>
                  </div>

                  {editando === chave ? (
                    <div className="flex items-center gap-1.5 shrink-0">
                      <input
                        autoFocus
                        value={valor}
                        onChange={e => setValor(e.target.value.replace(/[^\d]/g, ''))}
                        onKeyDown={e => { if (e.key === 'Enter') salvar(a) }}
                        inputMode="numeric"
                        placeholder="-"
                        className="w-14 bg-surface-2 border border-line rounded-md px-2 py-1
                                   text-center text-ink-1"
                      />
                      <Button size="sm" onClick={() => salvar(a)} disabled={salvando}>
                        <Check className="w-3.5 h-3.5" />
                      </Button>
                      <button type="button" className="text-ink-4 hover:text-ink-2 px-1"
                              onClick={() => { setEditando(null); setValor('') }}>
                        cancelar
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => { setEditando(chave); setValor('') }}
                      className="shrink-0 flex items-center gap-1.5 text-ink-3 hover:text-ink-1
                                 border border-line rounded-md px-2.5 py-1.5"
                    >
                      <Pencil className="w-3 h-3" />
                      preencher
                    </button>
                  )}
                </li>
              )
            })}
          </ul>

          <Pagination
            page={pagina}
            pageSize={15}
            total={lista.total}
            onChange={setPagina}
            unit="atuações"
          />
        </>
      )}

      {erro && (
        <p className="flex items-center gap-1.5 text-[11px] text-red-400">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          {erro}
        </p>
      )}
    </div>
  )
}
