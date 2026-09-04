import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'

import api from '../services/api'
import { rotuloDoMercado } from '../utils/marketTranslate'
import {
  Button, PanelHead, Panel, PickTypeBadge, ResultBadge, SectionHead, Spinner,
} from '../components/ui'
import { TeamLogo } from '../components/TeamLogo'
import PipelineProfitChart from '../components/PipelineProfitChart'
import { fmtUnits } from '../utils/format'
import { PICK_TYPE_LABEL } from '../utils/resultStyle'
import { usePertoDaTela } from '../hooks/usePertoDaTela'
import type { PublicSummary } from './StatsBand'
import type { RecentTip } from './tipos'

/*
 * A seção de resultados da Home · MORA FORA DO Home.tsx DE PROPÓSITO.
 *
 * Ela fica abaixo da dobra e arrasta junto o gráfico, os escudos e a tradução
 * de mercado. Enquanto estava dentro do Home.tsx, tudo isso entrava no chunk
 * da primeira tela e era baixado e avaliado antes de o visitante ler o título.
 * Em arquivo próprio ela vira `lazy()` (ver pages/Home.tsx) e só chega quando
 * a seção vai nascer.
 */

/* ── Últimos resultados ─────────────────────────────────────────────────── */

const PAGE_SIZE = 10

export default function RecentResults({ summary }: { summary: PublicSummary | null }) {
  /*
   * As duas chamadas desta seção só saem quando ela chega perto da tela.
   *
   * Ela vive lá embaixo, depois do hero, da dica do dia, da fila de jogos e
   * dos indicadores · ninguém a está lendo no primeiro segundo. Enquanto elas
   * saíam no `mount`, disputavam o mesmo worker com as três chamadas do topo,
   * e o PageSpeed de 04/09 mediu o resultado disso: seis requisições públicas
   * simultâneas, todas entre 4,6s e 6,3s, que sozinhas custam menos de 2s.
   */
  const [secao, perto] = usePertoDaTela<HTMLElement>()
  const [page, setPage]       = useState(0)
  const [produto, setProduto] = useState<string | null>(null)
  const [recent, setRecent]   = useState<RecentTip[]>([])
  const [total, setTotal]     = useState(0)
  const [pageLoading, setPageLoading] = useState(true)

  /* Produtos observados na janela atual (para os chips de filtro). */
  const produtos = useMemo(() => {
    const vistos: string[] = []
    for (const t of recent) if (!vistos.includes(t.source)) vistos.push(t.source)
    return vistos
  }, [recent])

  /* Toda vez que página ou filtro de produto mudam, busca no backend. */
  useEffect(() => {
    if (!perto) return
    setPageLoading(true)
    const params: Record<string, unknown> = {
      recent_limit:  PAGE_SIZE,
      recent_offset: page * PAGE_SIZE,
      slim: 1,
    }
    if (produto) params.source = produto
    api.get('/public/results', { params })
      .then(r => {
        setRecent(r.data?.recent ?? [])
        setTotal(r.data?.recent_total ?? 0)
      })
      .catch(() => { setRecent([]); setTotal(0) })
      .finally(() => setPageLoading(false))
  }, [page, produto, perto])

  /* Ao trocar filtro de produto, volta pra página 0. */
  const handleProduto = (p: string | null) => {
    setProduto(p)
    setPage(0)
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  const resumo = summary

  /*
   * Curva de lucro por produto · a prova mais forte que esta seção tem.
   */
  const [curva, setCurva] = useState<Array<{ match_date: string; source: string; profit: number }>>([])
  useEffect(() => {
    if (!perto) return
    api.get('/public/profit-curve', { params: { days: 180 } })
      .then(r => setCurva(r.data ?? []))
      .catch(() => setCurva([]))
  }, [perto])

  return (
    <section id="resultados" ref={secao} className="section section-alt">
      <div className="shell">
        <SectionHead
          title="Resultados reais, verificáveis"
          sub="Todo pick publicado fica registrado. Qualquer pessoa pode conferir, sem conta."
        />

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '0px 0px -80px 0px' }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        >
          {curva.length > 0 && (
            <Panel className="mb-4">
              <PanelHead
                label="Lucro acumulado por produto"
                meta="em unidades, últimos 180 dias"
              />
              <div className="p-5">
                <PipelineProfitChart data={curva} height={220} />
              </div>
            </Panel>
          )}

          <Panel>
            <PanelHead
              label="Últimas finalizadas"
              meta={`${total > 0 ? `${total} picks` : ''}${produto ? `, só ${PICK_TYPE_LABEL[produto] ?? produto}` : ', ordenados por data e hora da partida'}`}
            />

            {/* Chips de filtro por produto — sempre visíveis quando há mais de um tipo */}
            <div className="flex flex-wrap gap-1.5 px-4 pt-3">
              {[null, ...produtos].map(chave => {
                const ativo = produto === chave
                return (
                  <button
                    key={chave ?? 'todos'}
                    onClick={() => handleProduto(chave)}
                    className={`text-[11px] font-semibold px-2.5 py-1.5 min-h-[32px] rounded-md border transition-colors ${
                      ativo
                        ? 'border-accent/50 bg-accent/10 text-accent-ink'
                        : 'border-line text-ink-3 hover:text-ink-2 hover:border-line-strong'}`}
                  >
                    {chave === null ? 'Todos' : (PICK_TYPE_LABEL[chave] ?? chave)}
                  </button>
                )
              })}
            </div>

            {pageLoading ? (
              <div className="flex justify-center py-10"><Spinner size="md" /></div>
            ) : recent.length === 0 ? (
              <p className="text-center text-ink-4 text-sm py-8">Nenhum resultado ainda.</p>
            ) : (
              <div className="divide-y divide-line/50">
                {recent.map((tip, i) => (
                  <div key={i} className="flex items-center gap-2 px-4 py-3">
                    {/* Data e hora da partida: ordenados cronologicamente, mais
                        recente no topo. Hora vem de `fixtures` (efêmera), então
                        picks antigos mostram só a data. */}
                    <span className="font-mono text-[10px] text-ink-4 tabular-nums shrink-0 w-10 leading-tight">
                      <span className="block">
                        {new Date(tip.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                      </span>
                      {tip.match_datetime && (
                        <span className="block text-ink-3">{tip.match_datetime.slice(11, 16)}</span>
                      )}
                    </span>

                    <PickTypeBadge type={tip.source} short />

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <TeamLogo id={tip.home_team_id} name={tip.home_team_name} size={16} />
                        <span className="text-xs text-ink-1 font-medium truncate">{tip.home_team_name}</span>
                        {tip.away_team_name && tip.away_team_name !== '--' && (
                          <>
                            <span className="text-ink-4 text-[10px] shrink-0">x</span>
                            <TeamLogo id={tip.away_team_id} name={tip.away_team_name} size={16} />
                            <span className="text-xs text-ink-1 font-medium truncate">{tip.away_team_name}</span>
                          </>
                        )}
                      </div>
                      <p className="text-[10px] text-ink-3 truncate mt-0.5">
                        {rotuloDoMercado(tip.market, tip.line)}
                      </p>
                    </div>

                    <span className="font-mono text-[11px] font-bold text-ink-2 tabular-nums shrink-0">
                      {Number(tip.odd).toFixed(2)}
                    </span>
                    <ResultBadge result={tip.result} />
                  </div>
                ))}
              </div>
            )}

            {/* Paginação */}
            <div className="px-4 py-3 border-t border-line flex items-center justify-between gap-2 flex-wrap">
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0 || pageLoading}
                className="text-xs font-semibold px-3 py-1.5 rounded-md border border-line text-ink-3 hover:text-ink-2 hover:border-line-strong disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                ← Anterior
              </button>
              <span className="text-[11px] text-ink-4 tabular-nums">
                {totalPages > 0 ? `Pág. ${page + 1} de ${totalPages}` : ''}
              </span>
              <button
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1 || pageLoading}
                className="text-xs font-semibold px-3 py-1.5 rounded-md border border-line text-ink-3 hover:text-ink-2 hover:border-line-strong disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                Próxima →
              </button>
            </div>

            <div className="px-5 pb-4 flex items-center justify-center gap-4 flex-wrap">
              <Button to="/resultados" variant="link" size="sm">Ver histórico completo</Button>
              <span className="text-ink-4">,</span>
              <Button to="/login?mode=register" variant="link" size="sm" className="text-accent-ink hover:text-accent-hover">
                Criar conta grátis
              </Button>
            </div>
          </Panel>

          {/* Fechamento da seção de prova. */}
          {resumo && resumo.total > 0 && (
            <div className="mt-8 text-center max-w-xl mx-auto">
              <p className="text-ink-1 text-sm font-semibold mb-1.5">
                São {resumo.total} picks publicados antes da bola rolar, com{' '}
                {resumo.greens} greens e {fmtUnits(Number(resumo.profit ?? 0), 1)} de lucro.
              </p>
              <p className="text-ink-3 text-xs leading-relaxed mb-4">
                Cada um deles fica registrado com data, mercado e odd, e o resultado é
                conferido contra a estatística oficial da partida. Você não precisa
                acreditar em nós: dá para abrir o histórico e conferir pick por pick,
                sem criar conta.
              </p>
              <Button to="/login?mode=register" size="lg" IconRight={ArrowRight}>
                Testar o VIP grátis por 2 dias
              </Button>
            </div>
          )}
        </motion.div>
      </div>
    </section>
  )
}
