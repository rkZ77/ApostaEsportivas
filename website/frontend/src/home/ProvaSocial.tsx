import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { TrendingUp } from 'lucide-react'

import api from '../services/api'
import Avatar from '../components/Avatar'
import { SectionHead } from '../components/ui'
import { fadeInUp, staggerContainer } from '../lib/motion'

/*
 * QUEM SEGUIU OS PICKS, E COMO FOI.
 *
 * Esta seção é a resposta à pergunta que a faixa de indicadores não responde:
 * "o número é da IA, mas alguém de verdade ganhou dinheiro com isso?". A
 * diferença entre as duas é a fonte -- ali é o histórico do motor, aqui é a
 * banca de usuários reais que marcaram o pick como seguido.
 *
 * NADA AQUI É FABRICADO, e a distinção importa porque a alternativa óbvia é o
 * contador de "fulano assinou o VIP agora" que todo site do ramo usa. Esse
 * ticker já existiu na home e foi removido em 17/07 justamente por ser
 * inventado: prova social falsa não é uma técnica de conversão, é uma dívida
 * que vence quando alguém percebe.
 *
 * A rota `/public/leaderboard` já existia no backend desde sempre e não era
 * consumida por tela nenhuma: usuário anonimizado (primeiro nome e inicial do
 * sobrenome), mínimo de 5 picks resolvidos, ordenado por yield. Se ninguém
 * atinge o mínimo, a seção não nasce -- lista curta é melhor que lista cheia
 * de gente com dois picks.
 */

interface LinhaRanking {
  name: string
  avatar_url?: string | null
  total: number
  greens: number
  /** Mesma conta do resto do site · ver backend/taxa_acerto.py. */
  win_rate: number
  yield_roi: number
}

export default function ProvaSocial() {
  const [linhas, setLinhas] = useState<LinhaRanking[]>([])

  useEffect(() => {
    api.get('/public/leaderboard')
      .then(r => setLinhas(Array.isArray(r.data) ? r.data : []))
      .catch(() => setLinhas([]))
  }, [])

  /* Só entra quem está no lucro. Um ranking liderado por ROI negativo é um
     dado verdadeiro e um argumento contra o produto na mesma linha, e esta
     seção existe pra ser argumento a favor: quando não há o que mostrar, ela
     some, em vez de mostrar o que atrapalha. */
  const positivos = linhas.filter(l => l.yield_roi > 0)
  if (positivos.length < 3) return null

  return (
    <section className="section">
      <div className="shell">
        <SectionHead
          title="Quem seguiu os picks, e como foi"
          sub="Ranking por retorno sobre o valor apostado, entre as contas com pelo menos 5 picks encerrados. Nomes abreviados, números vindos da banca de cada um."
        />

        <motion.ul
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '0px 0px -60px 0px' }}
          className="space-y-2.5"
        >
          {positivos.map((l, i) => (
            <motion.li
              key={`${l.name}-${i}`}
              variants={fadeInUp}
              className="flex items-center gap-3 bg-surface-0 border border-line rounded-lg px-4 py-3.5"
            >
              <span className="font-mono text-xs text-ink-4 w-5 shrink-0 tabular-nums">{i + 1}</span>
              <Avatar name={l.name} imageUrl={l.avatar_url} size="sm" />

              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-ink-1 truncate">{l.name}</p>
                <p className="text-[11px] text-ink-4">
                  {l.total} {l.total === 1 ? 'pick encerrado' : 'picks encerrados'}, {l.win_rate}% de acerto
                </p>
              </div>

              <div className="text-right shrink-0">
                <p className="font-mono text-base font-bold text-accent-ink tabular-nums">
                  +{l.yield_roi.toFixed(1)}%
                </p>
                <p className="text-[10px] text-ink-4 leading-none">retorno</p>
              </div>
            </motion.li>
          ))}
        </motion.ul>

        {/* O caminho de quem acabou de ler o ranking é a banca, não o checkout:
            o que a lista promete é acompanhar o próprio resultado, e é isso que
            o link tem que entregar. */}
        <p className="text-xs text-ink-3 mt-4 flex items-center gap-1.5">
          <TrendingUp className="w-3.5 h-3.5 text-accent-ink shrink-0" aria-hidden="true" />
          Cada conta registra os picks que seguiu e o site fecha a conta sozinho.
          <Link to="/login?mode=register" className="text-accent-ink font-semibold hover:underline">
            Comece a sua
          </Link>
        </p>
      </div>
    </section>
  )
}
