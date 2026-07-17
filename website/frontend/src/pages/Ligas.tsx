import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Helmet } from 'react-helmet-async'
import { ArrowRight } from 'lucide-react'
import api from '../services/api'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'

interface League { league_id: number; name: string; season: number; logo_url: string }

function LeagueIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <circle cx="12" cy="12" r="10" strokeOpacity={0.5} />
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" strokeOpacity={0.5} />
      <path d="M2 12h20" strokeOpacity={0.5} />
    </svg>
  )
}

const PROCESSO = [
  {
    n: '01', color: 'text-green-500', bg: 'bg-green-500/10 border-green-500/20',
    title: 'Coleta de dados',
    desc: 'Estatísticas completas de cada jogo de cada liga coberta: gols, escanteios, cartões, posse, forma recente e confrontos diretos.',
  },
  {
    n: '02', color: 'text-blue-400', bg: 'bg-blue-400/10 border-blue-400/20',
    title: 'Análise estatística',
    desc: 'A IA calcula médias por contexto (casa/fora), tendências recentes, força ofensiva e defensiva. Compara probabilidades reais com as odds do mercado para encontrar edge.',
  },
  {
    n: '03', color: 'text-yellow-400', bg: 'bg-yellow-400/10 border-yellow-400/20',
    title: 'Geração de picks',
    desc: 'Apenas recomendações com EV positivo e confiança mínima entram no sistema. Picks VIP, Múltiplas e Alavancagem gerados automaticamente todo dia, para todas as ligas ativas.',
  },
]

const MERCADOS = ['Gols Over/Under', 'Ambas marcam', '1X2', 'Handicap Asiático', 'Total Escanteios', 'Cartões', 'Gols 1º Tempo']

export default function Ligas() {
  const [leagues, setLeagues] = useState<League[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/public/leagues')
      .then(r => setLeagues(r.data ?? []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <>
      <Helmet>
        <title>Ligas cobertas · Pick IA</title>
        <meta name="description" content="Veja todas as ligas e torneios de futebol cobertos pela Pick IA e como a inteligência artificial analisa cada uma para gerar picks diários." />
        <link rel="canonical" href="https://pickia.com.br/ligas" />
      </Helmet>
      <Navbar />
      <div className="min-h-screen bg-black text-white">
        <div className="max-w-3xl mx-auto px-4 pt-12 pb-8 text-center">
          <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-full px-4 py-1.5 mb-6">
            <span className="text-green-400 text-xs font-bold">Ligas &amp; torneios</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-black mb-4 leading-tight">
            Onde a IA já está<br /><span className="text-green-500">gerando picks</span>
          </h1>
          <p className="text-zinc-400 text-sm max-w-lg mx-auto leading-relaxed">
            A cobertura entra automaticamente assim que a temporada de cada liga estiver rolando.
            Veja o que está ativo agora e como a IA analisa cada um dos jogos.
          </p>
        </div>

        <div className="max-w-3xl mx-auto px-4 pb-10">
          {loading ? (
            <div className="flex justify-center py-8">
              <div className="w-6 h-6 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
            </div>
          ) : leagues.length > 0 ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              {leagues.map(({ league_id, name, season, logo_url }) => (
                <div key={league_id} className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex flex-col items-center gap-2 text-center">
                  <div className="w-12 h-12 relative flex items-center justify-center">
                    <img
                      src={logo_url}
                      alt={name}
                      className="w-12 h-12 object-contain"
                      onError={e => {
                        e.currentTarget.style.display = 'none'
                        const fb = e.currentTarget.nextElementSibling as HTMLElement
                        if (fb) fb.style.display = 'flex'
                      }}
                    />
                    <div className="absolute inset-0 items-center justify-center hidden">
                      <LeagueIcon className="w-9 h-9 text-zinc-600" />
                    </div>
                  </div>
                  <p className="text-sm font-bold text-white leading-tight">{name}</p>
                  <p className="text-[10px] text-zinc-500">{season}</p>
                  <span className="text-[10px] text-green-500 font-bold">Ativo</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-center text-zinc-600 text-sm py-8">Nenhuma liga ativa no momento.</p>
          )}
        </div>

        <div className="max-w-3xl mx-auto px-4 pb-10">
          <div className="text-center mb-8">
            <h2 className="text-2xl font-black mb-2">Como a IA gera os picks</h2>
            <p className="text-zinc-400 text-sm max-w-lg mx-auto">
              Não é palpite. É processamento de dados em escala, análise estatística e modelos
              treinados para o mercado de apostas esportivas — o mesmo processo para qualquer liga coberta.
            </p>
          </div>
          <div className="grid sm:grid-cols-3 gap-4">
            {PROCESSO.map(({ n, color, bg, title, desc }) => (
              <div key={n} className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 relative overflow-hidden">
                <div className={`absolute -top-3 -right-3 text-6xl font-black opacity-5 ${color}`}>{n}</div>
                <div className={`inline-flex items-center justify-center w-9 h-9 rounded-xl border text-sm font-black mb-3 ${bg} ${color}`}>{n}</div>
                <h3 className="text-sm font-black text-white mb-1.5">{title}</h3>
                <p className="text-zinc-400 text-xs leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
            <p className="text-xs text-zinc-500 font-medium mb-4">Mercados analisados</p>
            <div className="flex flex-wrap gap-2">
              {MERCADOS.map(m => (
                <span key={m} className="bg-zinc-800 border border-zinc-700/60 text-zinc-300 text-xs font-medium px-3 py-1.5 rounded-lg">
                  {m}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="max-w-3xl mx-auto px-4 pb-16 text-center">
          <div className="bg-zinc-900 border border-green-500/20 rounded-2xl p-8">
            <h2 className="text-xl font-black mb-2">Quer ver os picks de hoje?</h2>
            <p className="text-zinc-400 text-sm mb-6">Crie sua conta grátis e ganhe 2 dias de acesso VIP completo.</p>
            <Link
              to="/login?mode=register"
              className="inline-flex items-center gap-2 bg-green-600 hover:bg-green-500 text-white font-bold px-8 py-3.5 rounded-xl transition-colors text-sm"
            >
              Criar conta grátis
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </div>
      <Footer />
    </>
  )
}
