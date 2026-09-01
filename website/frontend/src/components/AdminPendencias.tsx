import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, RefreshCw, Wrench } from 'lucide-react'
import api from '../services/api'
import { Spinner } from './ui'

/*
 * Picks que já deviam ter fechado e continuam sem resultado.
 *
 * Estatística ausente nunca vira RED, e isso está certo: é a invariante que
 * nasceu de um pick de escanteios ser gravado RED porque a folha do jogo ainda
 * não tinha chegado no apito final. O efeito colateral é que "não liquida e
 * espera" não faz barulho, então um pick pode ficar pendente para sempre sem
 * ninguém perceber. Esta tela é o barulho que faltava.
 *
 * O motivo é o que torna a lista acionável, porque cada um pede uma ação
 * diferente: sem folha espera o collector, folha incompleta é o mesmo problema
 * pela metade, e folha completa aponta para a liquidação em vez da fonte.
 */

interface Item {
  travado: boolean
  pick_type: string
  id: number
  home_team: string | null
  away_team: string | null
  match_date: string | null
  market: string | null
  line: string | null
  fixture_id: number | null
  motivo: string
}

interface Dados {
  total: number
  simples: number
  travados: number
  aguardando_jogo: number
  horas_de_corte: number
  bilhetes: Record<string, number>
  por_motivo: Record<string, number>
  itens: Item[]
}

const COR_MOTIVO: Record<string, string> = {
  'sem folha do jogo': 'text-amber-400',
  'folha incompleta':  'text-orange-400',
  'folha completa':    'text-red-400',
}

export default function AdminPendencias() {
  const [dados, setDados] = useState<Dados | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [reparo, setReparo] = useState<any>(null)
  const [reparando, setReparando] = useState(false)
  const [erro, setErro] = useState('')

  const buscar = useCallback(async () => {
    setCarregando(true)
    try {
      const { data } = await api.get('/admin/picks/pendentes')
      setDados(data)
    } catch (e: any) {
      setErro(e.response?.data?.detail || 'Falha ao carregar pendências.')
    } finally {
      setCarregando(false)
    }
  }, [])

  useEffect(() => { buscar() }, [buscar])

  const descartar = async (i: Item) => {
    if (!window.confirm(
      `Descartar o pick ${i.pick_type} #${i.id} (${i.home_team} x ${i.away_team})?

` +
      'Use só para pick que NUNCA vai resolver, como fixture que não existe na API. ' +
      'O pick e os follows dele são apagados.'
    )) return
    try {
      await api.post('/admin/picks/descartar', { pick_type: i.pick_type, pick_id: i.id })
      buscar()
    } catch (e: any) {
      setErro(e.response?.data?.detail || 'Falha ao descartar.')
    }
  }

  const repararPernas = async (aplicar: boolean) => {
    setReparando(true)
    setErro('')
    try {
      const { data } = await api.post('/admin/picks/reparar-pernas', null, {
        params: { dry_run: !aplicar, limit: 30 },
      })
      setReparo(data)
    } catch (e: any) {
      setErro(e.response?.data?.detail || 'Falha no reparo.')
    } finally {
      setReparando(false)
    }
  }

  if (carregando && !dados) return <div className="flex justify-center py-12"><Spinner /></div>

  return (
    <div className="space-y-4">
      {/* Cards no mesmo formato da Visão geral */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { l: 'Aguardando o jogo', v: dados?.aguardando_jogo ?? 0,
            sub: 'normal, ainda vai rolar' },
          { l: 'Travados',        v: dados?.travados ?? 0,
            sub: `passou de ${dados?.horas_de_corte ?? 4}h do jogo`,
            c: (dados?.travados ?? 0) > 0 ? 'text-amber-400' : 'text-ink-1' },
          { l: 'Sem folha',       v: dados?.por_motivo?.['sem folha do jogo'] ?? 0,
            sub: 'esperando o collector' },
          { l: 'Folha completa',  v: dados?.por_motivo?.['folha completa'] ?? 0,
            sub: 'suspeita na liquidação',
            c: (dados?.por_motivo?.['folha completa'] ?? 0) > 0 ? 'text-red-400' : 'text-ink-1' },
        ].map(x => (
          <div key={x.l} className="bg-surface-1 border border-line rounded-lg px-4 py-3">
            <div className={`font-mono text-2xl font-black ${x.c ?? 'text-ink-1'}`}>{x.v}</div>
            <div className="text-xs text-ink-3 mt-0.5">{x.l}</div>
            {x.sub && <div className="text-[10px] text-ink-4 mt-0.5">{x.sub}</div>}
          </div>
        ))}
      </div>

      {erro && <p className="text-xs text-red-400">{erro}</p>}

      {/* Reparo das pernas de múltipla */}
      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div>
            <h3 className="text-xs font-semibold text-ink-3 flex items-center gap-1.5">
              <Wrench className="w-3.5 h-3.5" /> Reparo das pernas de múltipla
            </h3>
            <p className="text-[11px] text-ink-4 mt-1 leading-relaxed">
              Havia um bug que, ao fechar uma múltipla no RED, marcava RED em <b>todas</b> as
              pernas dela, inclusive nas que ganharam ou nem tinham jogado. O bilhete estava
              certo (uma perna perdida mata a múltipla), e o que ficou errado foi o detalhe
              de cada perna.
              <br /><br />
              Este botão relê cada perna dos bilhetes já fechados e reescreve só o detalhe.
              Ele <b>não</b> mexe no resultado nem no lucro do bilhete, então sua banca não
              muda. Simular mostra o que ele faria; nada é gravado até você aplicar.
              <br /><br />
              <span className="text-ink-3">Se der "0 com perna divergente", está tudo certo
              e não há nada para reparar.</span>
            </p>
          </div>
          <button onClick={buscar} className="shrink-0 text-ink-4 hover:text-ink-1 transition-colors" aria-label="Atualizar">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-3">
          <button
            onClick={() => repararPernas(false)}
            disabled={reparando}
            className="text-[11px] px-3 py-1.5 rounded-md border border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-1 transition-colors disabled:opacity-30"
          >
            {reparando ? 'analisando...' : 'Simular (não grava)'}
          </button>
          {reparo && reparo.divergentes > 0 && (
            <button
              onClick={() => repararPernas(true)}
              disabled={reparando}
              className="text-[11px] px-3 py-1.5 rounded-md bg-amber-500 hover:bg-amber-400 text-surface-0 font-black transition-colors disabled:opacity-30"
            >
              Aplicar em {reparo.divergentes}
            </button>
          )}
        </div>

        {reparo && (
          <div className="mt-3">
            <p className="text-[11px] text-ink-3">
              {reparo.analisados} analisados, {reparo.divergentes} com perna divergente
              {reparo.corrigidos > 0 && <span className="text-green-400 font-semibold">, {reparo.corrigidos} corrigidos</span>}
            </p>
            {reparo.mudancas?.length > 0 && (
              <ul className="mt-2 space-y-1">
                {reparo.mudancas.map((m: any) => (
                  <li key={m.pick_id} className="text-[11px] text-ink-4 font-mono">
                    #{m.pick_id} ({m.bilhete}): [{m.antes.map((x: any) => x ?? 'null').join(', ')}]
                    {' → '}
                    <span className="text-ink-2">[{m.depois.map((x: any) => x ?? 'null').join(', ')}]</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Lista */}
      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <h3 className="text-xs font-semibold text-ink-3 mb-3">
          Picks sem resultado
          {dados && Object.entries(dados.bilhetes).some(([, n]) => n > 0) && (
            <span className="text-ink-4 font-normal">
              {' '}(mais {Object.entries(dados.bilhetes).filter(([, n]) => n > 0)
                .map(([k, n]) => `${n} ${k}`).join(', ')})
            </span>
          )}
        </h3>
        {!dados?.itens?.length ? (
          <p className="text-[11px] text-ink-4 flex items-center gap-1.5">
            Nada pendente. Tudo que já jogou foi liquidado.
          </p>
        ) : (
          <>
          {/* Celular: cartao por pick. A tabela de seis colunas so cabia com
              rolagem lateral, e rolagem lateral dentro de pagina que ja rola
              pra baixo e a forma mais rapida de perder a linha que se estava
              lendo. O site e usado muito mais no celular que no PC. */}
          <ul className="sm:hidden divide-y divide-line/60 -mx-1">
            {dados.itens.map(i => (
              <li key={`m-${i.pick_type}-${i.id}`} className="py-3 px-1">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[12px] text-ink-2 font-semibold leading-snug">
                    {i.home_team} x {i.away_team}
                  </span>
                  <span className={`text-[10px] font-bold shrink-0 ${i.travado ? (COR_MOTIVO[i.motivo] ?? 'text-ink-3') : 'text-ink-4'}`}>
                    {i.travado ? i.motivo : 'aguardando'}
                  </span>
                </div>
                <p className="text-[11px] text-ink-3 mt-0.5">{i.market} {i.line}</p>
                <p className="text-[10px] text-ink-4 font-mono mt-0.5">
                  {i.match_date}, {i.pick_type}, fixture {i.fixture_id ?? 'sem'}
                </p>
              </li>
            ))}
          </ul>

          <div className="hidden sm:block overflow-x-auto -mx-4 px-4">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-ink-4 text-left border-b border-line">
                  <th className="pb-2 font-medium">Data</th>
                  <th className="pb-2 font-medium">Tipo</th>
                  <th className="pb-2 font-medium">Jogo</th>
                  <th className="pb-2 font-medium">Mercado</th>
                  <th className="pb-2 font-medium">Fixture</th>
                  <th className="pb-2 font-medium">Motivo</th>
                  <th className="pb-2 font-medium"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {dados.itens.map(i => (
                  <tr key={`${i.pick_type}-${i.id}`}>
                    <td className="py-2 pr-2 text-ink-4 font-mono whitespace-nowrap">{i.match_date}</td>
                    <td className="py-2 pr-2 text-ink-3">{i.pick_type}</td>
                    <td className="py-2 pr-2 text-ink-2 max-w-[170px] truncate">
                      {i.home_team} x {i.away_team}
                    </td>
                    <td className="py-2 pr-2 text-ink-3 max-w-[150px] truncate">{i.market} {i.line}</td>
                    <td className="py-2 pr-2 text-ink-4 font-mono">{i.fixture_id ?? '-'}</td>
                    <td className={`py-2 font-semibold ${i.travado ? (COR_MOTIVO[i.motivo] ?? 'text-ink-3') : 'text-ink-4'}`}>
                      {i.travado ? i.motivo : 'aguardando o jogo'}
                    </td>
                    <td className="py-2 text-right">
                      {/* So' pra fixture sintetica: e o unico caso em que da pra
                          afirmar que o pick NUNCA vai resolver. Nos outros o
                          dado pode chegar atrasado, e apagar seria perder pick
                          bom por impaciencia. */}
                      {(i.fixture_id ?? 0) >= 9000000 && (
                        <button
                          onClick={() => descartar(i)}
                          className="text-[10px] px-2 py-1 rounded border border-red-500/30 text-red-400 hover:bg-red-500/10 transition-colors"
                        >
                          Descartar
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
        {/* Fixture que a API não conhece nunca vai resolver sozinha, e fica
            pedindo sync a cada rodada do checker. Vale o aviso separado. */}
        {dados?.itens?.some(i => (i.fixture_id ?? 0) >= 9000000) && (
          <div className="mt-3 flex items-start gap-2 rounded-md border border-red-500/25 bg-red-500/[0.07] px-3 py-2">
            <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-ink-2 leading-relaxed">
              Tem pick com fixture acima de 9.000.000, que é faixa sintética e não existe na
              API-Football. Esses nunca vão resolver e vão pedir sync em toda rodada do checker.
              O caminho é apagar o pick, não esperar.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
