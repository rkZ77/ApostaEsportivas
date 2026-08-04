import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Zap, TrendingUp, BarChart2, Wallet, Bot, BookOpen, ArrowRight, Check, X } from 'lucide-react'
import PageShell from '../components/PageShell'
import { Button } from '../components/ui'
import { fadeInUp, staggerContainer } from '../lib/motion'

const features = [
  {
    icon: Zap,
    color: 'text-yellow-400',
    bg: 'bg-yellow-500/10 border-yellow-500/20',
    badge: 'VIP',
    badgeColor: 'bg-yellow-500/20 text-yellow-400',
    title: 'Picks VIP',
    desc: 'Picks diários gerados por IA com análise estatística completa. Publicados até às 12h com raciocínio detalhado, odd, mercado e sugestão de stake baseado na sua banca.',
    items: ['Publicados diariamente até às 12h', 'Kelly Criterion para gestão de banca', 'Análise de confiança e EV'],
  },
  {
    icon: BookOpen,
    color: 'text-green-400',
    bg: 'bg-green-500/10 border-green-500/20',
    badge: 'Free',
    badgeColor: 'bg-green-500/20 text-green-400',
    title: 'Dica do Dia',
    desc: 'Pick gratuito disponível para todos os usuários. A IA seleciona o mercado com maior taxa histórica do dia para você testar a plataforma.',
    items: ['Disponível para plano free', 'Mercado com maior taxa histórica', 'Ótimo para começar'],
  },
  {
    icon: TrendingUp,
    color: 'text-orange-400',
    bg: 'bg-orange-500/10 border-orange-500/20',
    badge: 'VIP',
    badgeColor: 'bg-yellow-500/20 text-yellow-400',
    title: 'Alavancagem',
    desc: 'Pick combinado (simples, dupla ou tripla) com odd entre 1.45 e 1.55. Ideal para crescimento constante de banca com risco controlado.',
    items: ['Odd combinada 1.45–1.55', 'Risco controlado por design', 'Exclusivo VIP'],
  },
  {
    icon: Zap,
    color: 'text-blue-400',
    bg: 'bg-blue-500/10 border-blue-500/20',
    badge: 'VIP',
    badgeColor: 'bg-yellow-500/20 text-yellow-400',
    title: 'Múltiplas',
    desc: 'Combinações de picks selecionados pela IA para potencializar o retorno. A IA só monta múltiplas quando os jogos passam nos critérios estatísticos.',
    items: ['2 a 4 seleções por múltipla', 'Critério estatístico rigoroso', 'Alta relação risco/retorno'],
  },
  {
    icon: Wallet,
    color: 'text-purple-400',
    bg: 'bg-purple-500/10 border-purple-500/20',
    badge: null,
    badgeColor: '',
    title: 'Minha Banca',
    desc: 'Registre suas apostas e acompanhe a evolução real da sua banca. A IA sugere o stake ideal para cada pick baseado no seu saldo atual.',
    items: ['Stake sugerido pelo Kelly Criterion', 'Evolução da banca em tempo real', 'Win rate e ROI calculados'],
  },
  {
    icon: Bot,
    color: 'text-cyan-400',
    bg: 'bg-cyan-500/10 border-cyan-500/20',
    badge: null,
    badgeColor: '',
    title: 'Agente IA',
    desc: 'Converse com uma IA especialista em futebol. Pergunte sobre qualquer jogo, seleção, mercado ou estratégia e receba análises baseadas nos dados reais do sistema.',
    items: ['Disponível 24/7', 'Analisa qualquer pick sob demanda', 'Explica odds e mercados'],
  },
  {
    icon: BarChart2,
    color: 'text-teal-400',
    bg: 'bg-teal-500/10 border-teal-500/20',
    badge: null,
    badgeColor: '',
    title: 'Resultados da IA',
    desc: 'Acompanhe o histórico de performance de todos os picks gerados. Filtre por tipo, período e veja a curva de lucro da IA ao longo do tempo.',
    items: ['Histórico completo de picks', 'ROI e win rate por período', 'VIP, Free, Múltipla e Alavancagem'],
  },
]

export default function ComoFunciona() {
  const navigate = useNavigate()

  const handleStart = () => {
    navigate('/picks', { replace: true })
  }

  const handleClose = () => {
    if (window.history.length > 1) navigate(-1)
    else navigate('/picks', { replace: true })
  }

  return (
    <PageShell
      title="Como funciona"
      description="Entenda como a IA do Pick IA analisa cada jogo, gera os picks e como usar cada parte da plataforma."
      width="prose"
      bar={{
        title: 'Como funciona',
        sub: 'Um tour por tudo que a plataforma faz',
        actions: (
          <Button variant="ghost" size="sm" Icon={X} onClick={handleClose}>
            Fechar
          </Button>
        ),
      }}
    >
      {/* Header */}
      <div className="pb-8 text-center">
        <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-sm px-4 py-1.5 mb-6">
          <span className="text-green-400 text-xs font-bold">Bem-vindo ao PickIA</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-bold mb-4 leading-tight">
          Como a plataforma<br />
          <span className="text-green-500">funciona</span>
        </h1>
        <p className="text-ink-2 text-sm max-w-lg mx-auto leading-relaxed">
          O PickIA usa inteligência artificial para gerar picks diários com base em dados estatísticos reais.
          Veja tudo que você tem disponível.
        </p>
      </div>

      {/* Feature cards */}
      <div className="pb-8">
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '0px 0px -80px 0px' }}
          className="space-y-4"
        >
          {features.map(({ icon: Icon, color, bg, badge, title, desc, items }) => (
            <motion.div key={title} variants={fadeInUp} whileHover={{ y: -2 }} className={`border rounded-lg p-5 ${bg}`}>
              <div className="flex items-start gap-3 sm:gap-4">
                <div className={`w-10 h-10 rounded-md flex items-center justify-center shrink-0 bg-surface-1 border border-line`}>
                  <Icon className={`w-5 h-5 ${color}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="font-display font-bold text-ink-1 text-sm">{title}</span>
                    {badge && (
                      <span className={badge === 'VIP' ? 'badge-vip' : 'badge-free'}>
                        {badge}
                      </span>
                    )}
                  </div>
                  <p className="text-ink-2 text-xs leading-relaxed mb-3">{desc}</p>
                  <ul className="space-y-1">
                    {items.map(item => (
                      <li key={item} className="flex items-center gap-2 text-xs text-ink-2">
                        <Check className={`w-3.5 h-3.5 shrink-0 ${color}`} />
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>

      {/* CTA */}
      <div className="pb-8 text-center">
        <div className="bg-surface-1 border border-line rounded-lg p-8">
          <h2 className="text-xl font-bold mb-2">Pronto para começar?</h2>
          <p className="text-ink-2 text-sm mb-6">
            Os picks de hoje já estão disponíveis. Confira as análises da IA.
          </p>
          <button
            onClick={handleStart}
            className="inline-flex items-center gap-2 bg-green-600 hover:bg-green-500 text-ink-1 font-bold px-8 py-3.5 rounded-md transition-colors text-sm"
          >
            Ver picks de hoje
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </PageShell>
  )
}
