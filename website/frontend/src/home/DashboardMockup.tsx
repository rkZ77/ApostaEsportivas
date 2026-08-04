import { motion } from 'framer-motion'
import { TrendingUp } from 'lucide-react'
import { Badge, LiveDot } from '../components/ui'

/*
 * Retrato do produto para o hero.
 *
 * Não é screenshot: é o próprio design system montando uma tela representativa,
 * com os mesmos tokens de superfície, borda e tipografia das telas reais. Assim
 * ele não envelhece junto com um PNG toda vez que a UI muda, e continua nítido
 * em qualquer densidade de pixel.
 *
 * Os números aqui são ILUSTRATIVOS e a peça diz isso em texto, no rodapé do
 * painel. Prova social de verdade fica logo abaixo, na faixa de indicadores,
 * que lê de /public/results.
 */

const ROWS = [
  { home: 'Palmeiras',  away: 'Fortaleza',   market: 'Over 1.5 gols',     odd: '1.42', conf: 82, ev: '+6.1%' },
  { home: 'Arsenal',    away: 'Brighton',    market: 'Ambas marcam',      odd: '1.78', conf: 74, ev: '+4.3%' },
  { home: 'Inter',      away: 'Atalanta',    market: 'Escanteios +8.5',   odd: '1.85', conf: 68, ev: '+3.2%' },
  { home: 'Girona',     away: 'Betis',       market: 'Faltas +21.5',      odd: '1.90', conf: 65, ev: '+2.8%' },
]

/** Barrinha de confiança. Verde só a partir de 70, que é o corte visual do site. */
function ConfBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <div className="w-8 h-1 rounded-full bg-surface-3 overflow-hidden hidden sm:block">
        <motion.div
          className={value >= 70 ? 'h-full bg-accent' : 'h-full bg-ink-4'}
          initial={{ width: 0 }}
          whileInView={{ width: `${value}%` }}
          viewport={{ once: true }}
          transition={{ duration: 0.8, delay: 0.3, ease: [0.2, 0, 0, 1] }}
        />
      </div>
      <span className="font-mono text-[10px] font-bold text-ink-2 tabular-nums w-6 text-right">
        {value}
      </span>
    </div>
  )
}

export default function DashboardMockup() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.25, ease: [0.16, 1, 0.3, 1] }}
      className="relative"
    >
      {/* Brilho por trás do painel. Puramente decorativo. */}
      <div
        aria-hidden="true"
        className="absolute -inset-8 bg-accent/10 blur-3xl rounded-full pointer-events-none"
      />

      <div className="relative panel shadow-elev">

        <div className="panel-head">
          <span className="flex items-center gap-2">
            <LiveDot />
            <span className="panel-label">Picks de hoje</span>
          </span>
          <Badge tone="green">EV positivo</Badge>
        </div>

        {/* Indicadores do topo */}
        <div className="grid grid-cols-3 divide-x divide-line border-b border-line">
          {[
            { label: 'Jogos lidos', value: '128' },
            { label: 'Aprovados',   value: '11' },
            { label: 'Confiança',   value: '72%' },
          ].map(({ label, value }) => (
            <div key={label} className="px-3 py-3 text-center">
              <div className="font-mono text-lg font-bold text-ink-1 tabular-nums">{value}</div>
              <div className="stat-label">{label}</div>
            </div>
          ))}
        </div>

        {/* Linhas de pick */}
        <div className="divide-y divide-line/50">
          {ROWS.map((r, i) => (
            <motion.div
              key={r.home}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.35, delay: 0.4 + i * 0.08, ease: 'easeOut' }}
              className="flex items-center gap-2 px-4 py-2.5"
            >
              <div className="flex-1 min-w-0">
                <p className="text-xs text-ink-1 font-medium truncate">
                  {r.home} <span className="text-ink-4">x</span> {r.away}
                </p>
                <p className="text-[10px] text-ink-3 truncate mt-0.5">{r.market}</p>
              </div>
              <span className="font-mono text-[11px] font-bold text-accent tabular-nums shrink-0 hidden sm:block">
                {r.ev}
              </span>
              <span className="font-mono text-[11px] font-bold text-ink-2 tabular-nums shrink-0 w-8 text-right">
                {r.odd}
              </span>
              <ConfBar value={r.conf} />
            </motion.div>
          ))}
        </div>

        <div className="px-4 py-2.5 border-t border-line flex items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 text-[10px] text-ink-4">
            <TrendingUp className="w-3 h-3" />
            Exemplo ilustrativo da tela de picks
          </span>
          <span className="panel-meta">Atualiza a cada análise</span>
        </div>
      </div>
    </motion.div>
  )
}
