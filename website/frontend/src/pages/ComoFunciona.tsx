import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Zap, TrendingUp, BarChart2, Wallet, Bot, BookOpen, ArrowRight, Check } from 'lucide-react'

const features = [
  {
    icon: Zap,
    color: 'text-yellow-400',
    bg: 'bg-yellow-500/10 border-yellow-500/20',
    badge: 'VIP',
    badgeColor: 'bg-yellow-500/20 text-yellow-400',
    title: 'Picks VIP',
    desc: 'Picks diários gerados por IA com análise estatística completa. Publicados às 07h com raciocínio detalhado, odd, mercado e sugestão de stake baseado na sua banca.',
    items: ['Publicados diariamente às 07h', 'Kelly Criterion para gestão de banca', 'Análise de confiança e EV'],
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
  const { user } = useAuth()

  const handleStart = () => {
    if (user) {
      localStorage.setItem(`pickia_onboarded_${user.id}`, '1')
    }
    navigate('/picks', { replace: true })
  }

  return (
    <div className="min-h-screen bg-black text-white">
      {/* Header */}
      <div className="max-w-3xl mx-auto px-4 pt-12 pb-8 text-center">
        <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-full px-4 py-1.5 mb-6">
          <span className="text-green-400 text-xs font-bold">Bem-vindo ao PickIA</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-black mb-4 leading-tight">
          Como a plataforma<br />
          <span className="text-green-500">funciona</span>
        </h1>
        <p className="text-zinc-400 text-sm max-w-lg mx-auto leading-relaxed">
          O PickIA usa inteligência artificial para gerar picks diários com base em dados estatísticos reais.
          Veja tudo que você tem disponível.
        </p>
      </div>

      {/* Feature cards */}
      <div className="max-w-3xl mx-auto px-4 pb-8">
        <div className="space-y-4">
          {features.map(({ icon: Icon, color, bg, badge, badgeColor, title, desc, items }) => (
            <div key={title} className={`border rounded-2xl p-5 ${bg}`}>
              <div className="flex items-start gap-4">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 bg-zinc-900 border border-zinc-800`}>
                  <Icon className={`w-5 h-5 ${color}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="font-black text-white text-sm">{title}</span>
                    {badge && (
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${badgeColor}`}>
                        {badge}
                      </span>
                    )}
                  </div>
                  <p className="text-zinc-400 text-xs leading-relaxed mb-3">{desc}</p>
                  <ul className="space-y-1">
                    {items.map(item => (
                      <li key={item} className="flex items-center gap-2 text-xs text-zinc-300">
                        <Check className={`w-3.5 h-3.5 shrink-0 ${color}`} />
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      <div className="max-w-3xl mx-auto px-4 pb-16 text-center">
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8">
          <h2 className="text-xl font-black mb-2">Pronto para começar?</h2>
          <p className="text-zinc-400 text-sm mb-6">
            Os picks de hoje já estão disponíveis. Confira as análises da IA.
          </p>
          <button
            onClick={handleStart}
            className="inline-flex items-center gap-2 bg-green-600 hover:bg-green-500 text-white font-bold px-8 py-3.5 rounded-xl transition-colors text-sm"
          >
            Ver picks de hoje
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
