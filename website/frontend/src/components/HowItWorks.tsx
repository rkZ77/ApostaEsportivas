import { Link } from 'react-router-dom'
import {
  Zap, TrendingUp, Wallet, Radio, BarChart2, Bot, Medal,
  ChevronRight, CheckCircle, Info, Lock, Layers, Target, Users,
} from 'lucide-react'

// ─── Bloco de passo numerado ───────────────────────────────────────────────────
function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4">
      <div className="shrink-0 w-8 h-8 rounded-full bg-green-500 flex items-center justify-center text-black font-black text-sm mt-0.5">
        {n}
      </div>
      <div className="flex-1 pb-6 border-b border-zinc-800/60 last:border-0 last:pb-0">
        <p className="font-black text-white text-sm mb-1.5">{title}</p>
        <div className="text-zinc-400 text-sm leading-relaxed space-y-1">{children}</div>
      </div>
    </div>
  )
}

// ─── Card de tipo de pick ──────────────────────────────────────────────────────
function PickTypeCard({ icon: Icon, title, badge, badgeCls, description, detail, free }: {
  icon: React.ElementType; title: string; badge: string; badgeCls: string
  description: string; detail: string; free?: boolean
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <div className="flex items-start gap-3 mb-2">
        <div className="w-9 h-9 rounded-lg bg-zinc-800 flex items-center justify-center shrink-0 mt-0.5">
          <Icon className="w-4.5 h-4.5 text-green-400" style={{ width: 18, height: 18 }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-black text-white text-sm">{title}</span>
            <span className={`text-[10px] font-bold uppercase tracking-wide border px-1.5 py-0.5 rounded ${badgeCls}`}>{badge}</span>
            {free && <span className="text-[10px] font-bold uppercase border px-1.5 py-0.5 rounded bg-green-500/10 text-green-400 border-green-500/20">GRÁTIS</span>}
          </div>
          <p className="text-zinc-400 text-xs mt-0.5">{description}</p>
        </div>
      </div>
      <p className="text-zinc-500 text-xs leading-relaxed ml-12">{detail}</p>
    </div>
  )
}

// ─── Card de glossário ─────────────────────────────────────────────────────────
function GlossCard({ term, def }: { term: string; def: string }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
      <span className="text-white font-black text-sm">{term} </span>
      <span className="text-zinc-400 text-xs leading-relaxed">{def}</span>
    </div>
  )
}

// ─── Principal ─────────────────────────────────────────────────────────────────
export default function HowItWorks() {
  return (
    <div className="space-y-8 pb-8">

      {/* Cabeçalho */}
      <div className="bg-gradient-to-br from-green-500/10 to-zinc-900 border border-green-500/20 rounded-2xl p-5">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-10 h-10 rounded-xl bg-green-500 flex items-center justify-center shrink-0">
            <Zap className="w-5 h-5 text-black" />
          </div>
          <div>
            <h2 className="font-black text-white text-base">Como funciona o PickIA</h2>
            <p className="text-zinc-500 text-xs">Tudo que você precisa saber para começar</p>
          </div>
        </div>
        <p className="text-zinc-400 text-sm leading-relaxed">
          O PickIA analisa estatísticas de jogos em tempo real e gera sugestões de apostas com edge real.
          Você acompanha, marca o que apostou e vê seu desempenho crescer.
        </p>
      </div>

      {/* Como começar */}
      <div>
        <h3 className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold mb-4">Primeiros passos</h3>
        <div className="space-y-4">
          <Step n={1} title="Configure sua banca">
            <p>Acesse a página <Link to="/banca" className="text-green-400 hover:text-green-300 font-semibold">Banca</Link> e informe:</p>
            <ul className="space-y-1 mt-1">
              <li className="flex items-center gap-2"><CheckCircle className="w-3.5 h-3.5 text-green-500 shrink-0" /><span>Banca inicial (quanto você tem para apostar)</span></li>
              <li className="flex items-center gap-2"><CheckCircle className="w-3.5 h-3.5 text-green-500 shrink-0" /><span>Valor da unidade (1u = quanto você aposta por pick, ex: R$20)</span></li>
              <li className="flex items-center gap-2"><CheckCircle className="w-3.5 h-3.5 text-green-500 shrink-0" /><span>Meta de banca (objetivo que quer atingir)</span></li>
            </ul>
            <div className="flex items-start gap-2 bg-zinc-800/60 rounded-lg px-3 py-2 mt-2">
              <Info className="w-3.5 h-3.5 text-zinc-500 shrink-0 mt-0.5" />
              <span className="text-xs text-zinc-500">Recomendamos 1u = 1–2% da banca total para gestão conservadora.</span>
            </div>
          </Step>

          <Step n={2} title="Explore os picks do dia">
            <p>Na aba <span className="text-white font-semibold">Hoje</span> você encontra os picks mais importantes do dia.
               Na aba <span className="text-white font-semibold">Picks Free</span> está a Dica do Dia — sugestão gratuita publicada diariamente.</p>
            <p className="mt-1">Com plano VIP, acesse todos os picks gerados pela IA nas abas <span className="text-yellow-400 font-semibold">Picks VIP</span>, <span className="text-yellow-400 font-semibold">Múltiplas</span> e <span className="text-yellow-400 font-semibold">Alavancagem</span>.</p>
          </Step>

          <Step n={3} title='Marque o que apostou com "+ Apostei"'>
            <p>Quando decidir apostar em um pick, clique em <span className="text-green-400 font-semibold">+ Apostei</span> no card do pick.
               Isso registra a aposta na sua banca e ativa o acompanhamento ao vivo.</p>
            <div className="flex items-start gap-2 bg-zinc-800/60 rounded-lg px-3 py-2 mt-2">
              <Info className="w-3.5 h-3.5 text-zinc-500 shrink-0 mt-0.5" />
              <span className="text-xs text-zinc-500">Apenas picks marcados como "Apostei" entram no seu Yield, ROI e Ranking.</span>
            </div>
          </Step>

          <Step n={4} title='Acompanhe ao vivo na aba "Ao Vivo"'>
            <p>Enquanto o jogo acontece, a aba <span className="text-red-400 font-semibold">Ao Vivo</span> mostra placar em tempo real, minuto do jogo e status do seu pick.</p>
            <p className="mt-1">Quando o resultado for confirmado, a banca e as estatísticas atualizam automaticamente.</p>
          </Step>

          <Step n={5} title="Analise seu desempenho">
            <p>Acesse <Link to="/results" className="text-green-400 hover:text-green-300 font-semibold">Resultados</Link> para ver Win Rate, lucro acumulado e histórico completo.
               Em <Link to="/banca" className="text-green-400 hover:text-green-300 font-semibold">Banca</Link> você vê a evolução do saldo e compara com o ROI da IA.</p>
          </Step>
        </div>
      </div>

      {/* Tipos de picks */}
      <div>
        <h3 className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold mb-4">Tipos de picks</h3>
        <div className="space-y-3">
          <PickTypeCard
            icon={Zap}
            title="Dica do Dia"
            badge="FREE"
            badgeCls="bg-green-500/10 text-green-400 border-green-500/20"
            free
            description="Uma sugestão publicada por dia, disponível para todos"
            detail="Publicada automaticamente após análise dos jogos do dia. Ideal para quem está começando ou quer testar a plataforma sem assinar."
          />
          <PickTypeCard
            icon={TrendingUp}
            title="Picks VIP"
            badge="VIP"
            badgeCls="bg-yellow-400/10 text-yellow-400 border-yellow-400/20"
            description="10–20 sugestões por dia com análise estatística completa"
            detail="Cada pick traz mercado, odd, casa de apostas, % de confiança da IA, EV (Edge Value) e reasoning detalhado com os dados que embasaram a sugestão."
          />
          <PickTypeCard
            icon={Layers}
            title="Múltiplas"
            badge="VIP"
            badgeCls="bg-yellow-400/10 text-yellow-400 border-yellow-400/20"
            description="Combinações de 2+ seleções para odd mais alta"
            detail="A IA monta combinações coerentes de picks do dia. Maior retorno, maior risco — ideal para apostadores que buscam odds acima de 3.0."
          />
          <PickTypeCard
            icon={Target}
            title="Alavancagem"
            badge="VIP"
            badgeCls="bg-yellow-400/10 text-yellow-400 border-yellow-400/20"
            description="Série progressiva para multiplicar a banca"
            detail="Método de reinvestimento: cada GREEN dobra o retorno no próximo pick. Estratégia agressiva com acompanhamento visual do caminho percorrido."
          />
        </div>
      </div>

      {/* Funcionalidades da plataforma */}
      <div>
        <h3 className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold mb-3">Explore a plataforma</h3>
        <div className="grid grid-cols-2 gap-2">
          {[
            { to: '/banca',       Icon: Wallet,   title: 'Banca',       desc: 'Gerencie seu bankroll e acompanhe o crescimento' },
            { to: '/fixtures',    Icon: BarChart2, title: 'Jogos',       desc: 'Veja a agenda e estatísticas detalhadas de partidas' },
            { to: '/results',     Icon: TrendingUp, title: 'Resultados', desc: 'Histórico completo com Win Rate, ROI e lucro' },
            { to: '/agente',      Icon: Bot,       title: 'Agente IA',   desc: 'Pergunte sobre picks, banca e análises ao chat' },
            { to: '/leaderboard', Icon: Medal,     title: 'Ranking',     desc: 'Compare seu Yield com outros apostadores' },
            { to: '/picks#aovivo', Icon: Radio,    title: 'Ao Vivo',     desc: 'Acompanhe seus picks em tempo real durante os jogos' },
          ].map(({ to, Icon, title, desc }) => (
            <Link key={to} to={to}
              className="bg-zinc-900 border border-zinc-800 hover:border-zinc-700 rounded-xl p-3.5 transition-colors group"
            >
              <Icon className="w-4 h-4 text-green-400 mb-2" />
              <p className="text-white text-xs font-bold mb-0.5">{title}</p>
              <p className="text-zinc-500 text-[11px] leading-snug">{desc}</p>
            </Link>
          ))}
        </div>
      </div>

      {/* Glossário */}
      <div>
        <h3 className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold mb-3">Termos importantes</h3>
        <div className="space-y-2">
          <GlossCard term="Confiança (%)" def="Probabilidade estimada pela IA de que o pick seja vencedor. Acima de 70% indica alta certeza estatística." />
          <GlossCard term="EV (Edge Value)" def="Quanto a odd paga além do risco real. EV positivo significa que a bet tem valor a longo prazo." />
          <GlossCard term="Odd" def="Multiplicador da aposta. Odd 1.85 com R$100 apostados retorna R$185 se GREEN." />
          <GlossCard term="Stake / Unidade (1u)" def="Valor base da aposta. Se 1u = R$20, um pick de 2u significa R$40 apostados." />
          <GlossCard term="Win Rate" def="% de picks vencedores sobre o total. 55%+ é considerado bom para apostas esportivas." />
          <GlossCard term="Yield" def="Lucro em unidades por pick jogado. Métrica mais honesta para avaliar um tipster a longo prazo." />
          <GlossCard term="ROI" def="Retorno sobre investimento em reais. Depende das odds médias e do Win Rate combinados." />
          <GlossCard term="Alavancagem" def="Estratégia em que você reinveste o retorno do pick anterior no próximo, crescendo a banca de forma acelerada." />
        </div>
      </div>

      {/* Planos */}
      <div className="bg-zinc-900 border border-yellow-500/20 rounded-2xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <Lock className="w-4 h-4 text-yellow-400" />
          <span className="text-white font-black text-sm">Free vs VIP</span>
        </div>
        <div className="space-y-2 text-sm">
          {[
            ['Dica do Dia (1 pick/dia)', true, true],
            ['Picks VIP (10–20/dia)', false, true],
            ['Múltiplas da IA', false, true],
            ['Alavancagem', false, true],
            ['Gestão de Banca completa', false, true],
            ['Ranking de apostadores', false, true],
            ['Agente IA (chat)', 'limitado', true],
          ].map(([feat, free, vip]) => (
            <div key={String(feat)} className="flex items-center justify-between">
              <span className="text-zinc-400 text-xs">{feat}</span>
              <div className="flex items-center gap-4">
                <span className={`text-[11px] font-semibold w-14 text-center ${free === true ? 'text-green-400' : free === 'limitado' ? 'text-zinc-500' : 'text-zinc-700'}`}>
                  {free === true ? 'Grátis' : free === 'limitado' ? 'Limitado' : '—'}
                </span>
                <span className="text-[11px] font-semibold text-yellow-400 w-10 text-center">VIP</span>
              </div>
            </div>
          ))}
        </div>
        <Link to="/planos" className="mt-4 flex items-center justify-center gap-2 w-full py-2.5 rounded-xl bg-yellow-500 hover:bg-yellow-400 text-black font-black text-sm transition-colors">
          Ver planos <ChevronRight className="w-4 h-4" />
        </Link>
      </div>

      {/* Dica final */}
      <div className="flex items-start gap-3 bg-green-500/5 border border-green-500/15 rounded-xl px-4 py-3">
        <Users className="w-4 h-4 text-green-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-white text-sm font-bold mb-0.5">Dica de quem já usa</p>
          <p className="text-zinc-400 text-xs leading-relaxed">
            Comece marcando apenas a Dica do Dia por 2 semanas para entender o fluxo.
            Configure 1u conservador (1% da banca) e suba gradualmente conforme o Win Rate aparecer nos Resultados.
          </p>
        </div>
      </div>

    </div>
  )
}
