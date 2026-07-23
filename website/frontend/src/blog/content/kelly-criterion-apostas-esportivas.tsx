import { Link } from 'react-router-dom'
import { P, H2, UL, OL, LI, Strong, Callout } from '../article-ui'

export default function KellyCriterionApostasEsportivas() {
  return (
    <>
      <P>
        Muita gente que aposta em futebol perde dinheiro não porque erra os palpites, mas
        porque aposta o valor errado em cada um deles. Apostar sempre o mesmo valor fixo, ou
        pior, aumentar o valor depois de uma perda para "recuperar", é a forma mais rápida de
        quebrar uma banca mesmo tendo picks com taxa de acerto boa. O <Strong>Kelly Criterion</Strong>{' '}
        resolve esse problema: é uma fórmula matemática que calcula qual fração da sua banca
        você deveria apostar em cada entrada, com base na probabilidade real de acerto e na odd
        oferecida.
      </P>

      <H2>O que é o Kelly Criterion</H2>
      <P>
        O Kelly Criterion foi desenvolvido em 1956 pelo cientista John Kelly Jr., nos laboratórios
        da Bell, para um problema de teoria da informação, mas acabou virando padrão em apostas e
        no mercado financeiro. Em apostas esportivas, ele responde a uma pergunta simples: dado
        que você acredita que uma aposta tem valor esperado positivo (EV+), qual fração da sua
        banca maximiza o crescimento no longo prazo sem expor você ao risco de ruína?
      </P>
      <P>
        A ideia central é que apostar demais em uma aposta boa é tão prejudicial quanto apostar
        de menos. Stake alto demais aumenta a chance de uma sequência de perdas te tirar do jogo
        antes de a vantagem estatística se manifestar. Stake baixo demais desperdiça uma vantagem
        real.
      </P>

      <H2>Por que isso importa para quem aposta em futebol</H2>
      <P>
        Futebol tem variância alta: um time favorito pode perder para um azarão em qualquer
        rodada, mesmo quando a análise estatística estava correta. Isso significa que mesmo picks
        com EV+ consistente vão ter sequências de vitórias e derrotas. Sem um critério de stake,
        é comum o apostador aumentar o valor depois de acertar (achando que "está em uma boa
        fase") ou depois de errar (tentando recuperar rápido). Os dois comportamentos destroem
        banca no médio prazo. O Kelly Criterion tira essa decisão da emoção e coloca na matemática.
      </P>

      <H2>A fórmula do Kelly Criterion</H2>
      <P>
        A versão simplificada da fórmula para apostas de resultado único é:
      </P>
      <Callout>
        f* = (b × p − q) / b, onde <Strong>f*</Strong> é a fração da banca a apostar,{' '}
        <Strong>b</Strong> é a odd decimal menos 1, <Strong>p</Strong> é a probabilidade estimada
        de acerto e <Strong>q</Strong> é a probabilidade de erro (1 − p).
      </Callout>
      <P>Na prática, calcular o stake ideal segue estes passos:</P>
      <OL>
        <LI>Estime a probabilidade real de acerto do evento (p), não a probabilidade implícita na odd.</LI>
        <LI>Calcule b subtraindo 1 da odd decimal oferecida pela casa.</LI>
        <LI>Aplique a fórmula f* = (b × p − q) / b para achar a fração ideal da banca.</LI>
        <LI>Se f* for negativo, a aposta não tem valor esperado positivo: não aposte.</LI>
        <LI>Multiplique f* pelo tamanho atual da sua banca para chegar no valor do stake.</LI>
      </OL>

      <H2>Um exemplo prático</H2>
      <P>
        Suponha uma banca de R$ 1.000, uma odd de 2.10 para a vitória de um time e uma
        probabilidade estimada de acerto de 55%. Aqui, b = 1.10, p = 0.55 e q = 0.45. Aplicando a
        fórmula: f* = (1.10 × 0.55 − 0.45) / 1.10 ≈ 0.14, ou seja, cerca de 14% da banca, o que
        daria um stake de R$ 140. Repare que o resultado depende inteiramente da qualidade da
        estimativa de probabilidade: se a probabilidade real fosse 50% em vez de 55%, o valor
        esperado desapareceria e o Kelly recomendaria não apostar.
      </P>

      <H2>Kelly fracionário: por que reduzir o risco na prática</H2>
      <P>
        O Kelly Criterion "puro" assume que sua estimativa de probabilidade está correta, o que
        raramente é 100% verdade. Por isso, a prática mais usada é o <Strong>Kelly fracionário</Strong>:
        apostar uma fração do valor calculado, geralmente metade (meio Kelly) ou um quarto (Kelly
        1/4). Isso reduz a volatilidade da banca em troca de um crescimento um pouco mais lento,
        e é a abordagem recomendada para quem está começando a aplicar gestão de banca de forma
        sistemática.
      </P>

      <H2>Erros comuns de gestão de banca</H2>
      <UL>
        <LI>Apostar valor fixo em toda entrada, ignorando a diferença de confiança entre picks.</LI>
        <LI>Aumentar o stake depois de uma sequência de perdas para tentar recuperar rápido.</LI>
        <LI>Usar a probabilidade implícita da própria odd como se fosse a probabilidade real do evento.</LI>
        <LI>Não ter uma banca separada e definida, misturando o valor de apostas com outras finanças.</LI>
        <LI>Aplicar o Kelly cheio sem margem de segurança para erro de estimativa.</LI>
      </UL>

      <H2>Como o Pick IA aplica isso por você</H2>
      <P>
        Calcular probabilidade real, valor esperado e fração de Kelly manualmente para cada jogo
        é trabalhoso, e pequenos erros de estimativa mudam o resultado. No <Strong>Pick IA</Strong>,
        cada pick VIP já vem com o mercado, a odd e o stake sugerido calculado a partir da
        probabilidade estimada pela IA, com base em forma recente dos times, histórico de
        confrontos e dados estatísticos. A ferramenta de{' '}
        <Link to="/banca" className="text-green-400 hover:underline">Minha Banca</Link> aplica
        esse cálculo automaticamente sobre o saldo atual, então você não precisa fazer a conta na
        mão a cada aposta.
      </P>

      <Callout>
        Kelly Criterion é uma ferramenta de gestão de risco, não uma garantia de lucro. Toda
        aposta esportiva envolve variância e a probabilidade de perda existe mesmo em entradas
        com valor esperado positivo. Aposte com responsabilidade. +18.
      </Callout>

      <P>
        Se você já entende o que é EV positivo mas ainda decide o valor da aposta "no olho", o
        Kelly fracionário é o próximo passo mais simples para proteger a banca no longo prazo. Para
        ver como isso funciona com picks reais, o plano{' '}
        <Link to="/planos" className="text-green-400 hover:underline">VIP do Pick IA</Link> inclui
        stake sugerido em todo pick, ou você pode{' '}
        <Link to="/login?mode=register" className="text-green-400 hover:underline">
          criar uma conta gratuita
        </Link>{' '}
        e testar com a Dica do Dia.
      </P>
    </>
  )
}
