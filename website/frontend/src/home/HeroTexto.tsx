import { ArrowRight } from 'lucide-react'
import { Button, LiveDot } from '../components/ui'

/*
 * A COLUNA ESQUERDA DO HERO · E O UNICO PEDACO DO SITE QUE EXISTE ANTES DO JS.
 *
 * Este arquivo esta separado do Home.tsx por um motivo de build, nao de
 * organizacao: `scripts/prerender-hero.mjs` o renderiza em HTML durante o
 * build e injeta o resultado dentro do <div id="root"> do index.html. Quando
 * o navegador recebe a pagina, o titulo, o paragrafo e os dois botoes ja
 * estao la, pintados, sem esperar bundle nenhum.
 *
 * POR QUE ISSO IMPORTA. O paragrafo abaixo e o elemento de LCP da Home. O
 * PageSpeed de 04/09 mediu 5,7s de LCP com TTFB zero e 2.340ms de "atraso de
 * renderizacao": o servidor respondia rapido e o texto esperava o React
 * montar. Nenhum ajuste de bundle resolve isso, porque o teto e o proprio
 * React existir · a unica saida e o texto nao depender dele.
 *
 * REGRAS PARA MEXER AQUI
 * ----------------------
 * 1. Nada de estado, efeito, contexto ou dado de API. O que entra aqui e
 *    renderizado fora do navegador, sem AuthProvider e sem Helmet.
 * 2. `Link` do react-router funciona (o script usa StaticRouter), mas hook de
 *    rota (useNavigate, useLocation) nao.
 * 3. Nao duplicar este markup no index.html. Ele e gerado A PARTIR daqui, e e
 *    por isso que nao pode divergir · a licao do preco fixo no JSON-LD, que
 *    anunciou R$ 49,90 pro Google enquanto a cobranca era R$ 39,90.
 *
 * A ANIMACAO E A PROP `animar`
 * ----------------------------
 * As classes `.entra` (index.css) sao CSS puro, entao a animacao de entrada
 * roda no HTML estatico, antes de qualquer JavaScript. Quando o React monta,
 * segundos depois numa conexao ruim, ele recria estes nos · e animar de novo
 * seria um segundo fade no texto que a pessoa ja leu. Por isso o Home passa
 * `animar={false}` quando encontra o hero estatico na pagina: o React assume o
 * estado final, sem repetir o efeito.
 */

/** As tres linhas do titulo. Uma por elemento porque a quebra e' escolhida,
 *  nao consequencia da largura da tela. */
const HEADLINE = ['Palpites de futebol', 'com valor calculado,', 'não com achismo.']

export default function HeroTexto({ animar = true }: { animar?: boolean }) {
  const entra = (extra: string) => (animar ? `entra ${extra} ` : '')

  return (
    <div>
      <div className={`${entra('entra-1')}inline-flex items-center gap-2 border border-line rounded-full pl-2 pr-3 py-1 mb-6`}>
        <LiveDot />
        <span className="text-[11px] font-medium text-ink-2">
          Análise rodando nas ligas em temporada
        </span>
      </div>

      <h1 className="font-display text-4xl md:text-5xl font-bold leading-[1.08] tracking-tight mb-5">
        {HEADLINE.map((line, i) => (
          <span
            key={line}
            className={`${animar ? 'entra ' : ''}block ${i === 1 ? 'text-accent-ink' : ''}`}
            style={animar ? { animationDelay: `${i * 40}ms` } : undefined}
          >
            {line}
          </span>
        ))}
      </h1>

      <p className={`${entra('entra-2')}text-ink-2 text-base leading-relaxed mb-7 max-w-lg`}>
        A Pick IA lê estatística real de cada jogo, calcula a probabilidade de cada
        mercado e compara com a odd que a casa está pagando. Só vira palpite o que
        tem valor esperado positivo.
      </p>

      <div className={`${entra('entra-3')}flex flex-col sm:flex-row gap-3 mb-4`}>
        {/* O rótulo lidera pelo que a pessoa GANHA, não pelo trabalho que ela
            tem. "Criar conta · 2 dias VIP grátis" abria com a tarefa (criar
            conta) e empurrava a recompensa pro fim, atrás de um separador · e
            "2 dias VIP grátis" solto ainda deixava no ar se o grátis era o VIP
            ou a conta. Aqui o verbo é testar, o objeto é o VIP e o preço
            aparece antes do clique. */}
        <Button to="/login?mode=register" size="lg" IconRight={ArrowRight}>
          Testar o VIP grátis por 2 dias
        </Button>
        <Button to="/resultados" variant="ghost" size="lg">
          Ver resultados reais
        </Button>
      </div>
    </div>
  )
}
