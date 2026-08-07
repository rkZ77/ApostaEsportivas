import { SectionHead } from '../components/ui'
import LeagueMarquee from '../components/LeagueMarquee'

/*
 * Ligas cobertas, como seção da Home.
 *
 * Estava no rodapé e aparecia nas 23 telas, inclusive pra quem já assinou.
 * É argumento de venda, então o lugar dela é aqui, uma vez só.
 *
 * Uma fita só, com cada liga uma vez.
 *
 * Eram duas cruzadas, em sentidos opostos, e cada uma rodava a lista inteira ·
 * ou seja, toda liga aparecia duas vezes na tela ao mesmo tempo, uma indo e
 * outra voltando. Somado à repetição que a fita fazia por dentro pra encher o
 * trilho, a mesma liga chegava a sair seis vezes. Lido de fora, isso não passa
 * a impressão de cobertura ampla: passa a de lista curta sendo esticada.
 *
 * Com uma fita só e a lista inteira nela, o trilho fica mais largo e a rolagem
 * tem mais chance de acontecer de verdade, em vez de ser preenchimento.
 */
export default function Leagues() {
  return (
    <section className="section-tight overflow-hidden">
      <div className="shell">
        <SectionHead
          title="As ligas que a IA analisa"
          sub="A cobertura entra e sai conforme a temporada de cada campeonato. A lista abaixo é o que está ativo agora."
        />
      </div>

      <LeagueMarquee />
    </section>
  )
}
