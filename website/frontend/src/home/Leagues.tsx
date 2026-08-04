import { SectionHead } from '../components/ui'
import LeagueMarquee from '../components/LeagueMarquee'

/*
 * Ligas cobertas, como seção da Home.
 *
 * Estava no rodapé e aparecia nas 23 telas, inclusive pra quem já assinou.
 * É argumento de venda, então o lugar dela é aqui, uma vez só.
 *
 * Duas fitas em direções opostas: uma só, sozinha na largura da tela, lê como
 * banner de patrocinador. Cruzadas, o movimento fica claramente decorativo e
 * o olho para nos escudos em vez de tentar acompanhar a rolagem.
 */
export default function Leagues() {
  return (
    <section className="section-tight overflow-hidden">
      <div className="shell">
        <SectionHead
          eyebrow="Cobertura"
          title="As ligas que a IA analisa"
          sub="A cobertura entra e sai conforme a temporada de cada campeonato. A lista abaixo é o que está ativo agora."
        />
      </div>

      <div className="space-y-3">
        <LeagueMarquee />
        <LeagueMarquee reverse />
      </div>
    </section>
  )
}
