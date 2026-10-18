import { Link } from 'react-router-dom'
import { P, H2, UL, OL, LI, Strong, Callout } from '../article-ui'

export default function ComoAnalisarUmJogoDeFutebol() {
  return (
    <>
      <P>
        Quase todo mundo que acompanha futebol já tem uma opinião sobre o jogo de domingo antes
        de ele começar. O time da casa vem bem, o visitante perdeu o artilheiro, o clássico
        sempre é pegado. Opinião não falta. O que falta é saber{' '}
        <Strong>como analisar um jogo de futebol</Strong> de um jeito que resista aos números:
        olhar os dados certos, no recorte certo, e desconfiar do que parece óbvio. Este texto
        mostra o caminho que usamos, do mais importante para o menos importante.
      </P>

      <H2>Forma recente: o número mais usado e o mais mal lido</H2>
      <P>
        Forma recente é o desempenho de um time nas últimas partidas, normalmente as últimas
        cinco. É o primeiro dado que todo mundo olha, e faz sentido: ele mostra o momento do
        time melhor do que a tabela da temporada inteira.
      </P>
      <P>
        O problema é o recorte. Cinco jogos misturados dizem pouco. Um time pode ter vencido
        quatro de cinco jogando três vezes em casa contra a parte de baixo da tabela. Antes de
        confiar na sequência, separe:
      </P>
      <UL>
        <LI>
          <Strong>Casa e fora.</Strong> Muitos times mudam de cara longe do próprio estádio.
          Para o jogo que você está analisando, a forma que interessa é a do mandante em casa e
          a do visitante fora.
        </LI>
        <LI>
          <Strong>Contra quem.</Strong> Vencer o lanterna e vencer um time do G6 não valem a
          mesma coisa. Veja como cada time se saiu contra adversários do nível do próximo.
        </LI>
        <LI>
          <Strong>Qual competição.</Strong> Jogo de copa com time misto entra na sequência e
          distorce a leitura do campeonato.
        </LI>
      </UL>
      <Callout>
        Uma sequência de vitórias só diz alguma coisa depois que você sabe onde e contra quem
        ela aconteceu.
      </Callout>

      <H2>Média de gols e o que ela esconde</H2>
      <P>
        A média de gols marcados e sofridos é o segundo dado mais citado. Ela resume o perfil
        do time: ataque que produz, defesa que segura, ou jogos abertos dos dois lados.
      </P>
      <P>
        A média, porém, esconde a distribuição. Pense em dois times com média de dois gols por
        jogo nas últimas cinco partidas. Um marcou dois em todas. O outro fez zero em três e
        cinco nas outras duas. Os números são iguais e os times são completamente diferentes.
        O primeiro é constante. O segundo depende de um jogo que destrava.
      </P>
      <P>
        Por isso vale olhar jogo a jogo, e não só o resumo. Em quantas partidas o time marcou?
        Em quantas sofreu? A média de gols em casa é parecida com a de fora? Com cinco jogos, um
        placar fora da curva muda a média inteira, então trate o número como pista, não como
        verdade.
      </P>

      <H2>Confronto direto: útil, mas com prazo de validade</H2>
      <P>
        Confronto direto, ou H2H, é o histórico de jogos entre os dois times. Ele aparece em
        toda pré-partida e costuma ser superestimado.
      </P>
      <P>
        Um clássico que terminou empatado nos últimos quatro encontros conta uma história, mas
        talvez esses jogos tenham acontecido com outros técnicos, outros elencos e outra fase
        dos dois times. Confronto de três temporadas atrás pesa muito pouco. O que costuma se
        manter é o estilo do jogo: clássicos travados, com muitas faltas e cartões, tendem a
        seguir assim mesmo com elencos novos.
      </P>
      <P>
        Use o confronto direto como desempate, depois da forma recente e da média de gols, e
        nunca como o argumento principal.
      </P>

      <H2>Escalação e desfalques mudam a análise inteira</H2>
      <P>
        Toda estatística de time foi produzida por um grupo de jogadores. Se o grupo muda, o
        número perde parte do valor. Um time que marca muito com o centroavante titular pode
        ser outro sem ele, e uma defesa sólida às vezes depende de um zagueiro só.
      </P>
      <P>
        Por isso a escalação provável e a lista de desfalques entram antes de qualquer
        conclusão. Os desfalques que mais pesam são o goleiro titular, o principal finalizador e
        o volante que protege a defesa. Quando um deles fica fora, vale olhar a estatística
        individual de quem entra: finalizações por jogo, passes certos, duelos ganhos e, no caso
        do goleiro, defesas por partida.
      </P>

      <H2>O árbitro também entra em campo</H2>
      <P>
        O árbitro é o dado mais esquecido de uma pré-partida. Alguns apitam pouco e deixam o jogo
        correr, outros param tudo e distribuem cartões. Para quem analisa disciplina, faltas ou o
        ritmo do jogo, isso faz diferença.
      </P>
      <P>
        O dado útil é a média de cartões e faltas por jogo do árbitro escalado. Cuidado com a
        amostra: dois ou três jogos não definem perfil nenhum. O ideal é olhar a temporada
        inteira do árbitro, em todas as competições que ele apitou no país, e comparar com a
        média da própria liga. Um árbitro com média de cartões bem acima da liga num clássico
        pegado é uma informação que poucos levam em conta.
      </P>

      <H2>Como analisar um jogo de futebol em 7 passos</H2>
      <P>
        Este é o roteiro prático, na ordem em que cada dado costuma pesar. Dá para fazer em
        poucos minutos quando os números estão reunidos num lugar só.
      </P>
      <OL>
        <LI>
          <Strong>Situe os dois times na tabela.</Strong> Quem briga por título, por vaga ou
          contra o rebaixamento muda a motivação e o risco que cada um aceita correr.
        </LI>
        <LI>
          <Strong>Leia a forma recente separando casa e fora.</Strong> Mandante em casa,
          visitante fora, sempre com o adversário enfrentado em mente.
        </LI>
        <LI>
          <Strong>Olhe os gols jogo a jogo.</Strong> Marcou em quantas partidas, sofreu em
          quantas, e se a média vem de um placar isolado.
        </LI>
        <LI>
          <Strong>Confira escalação e desfalques.</Strong> Se uma peça importante está fora,
          ajuste a leitura dos passos anteriores.
        </LI>
        <LI>
          <Strong>Veja o confronto direto recente.</Strong> Só os encontros das duas últimas
          temporadas, e só como desempate.
        </LI>
        <LI>
          <Strong>Cheque o árbitro.</Strong> Média de cartões e faltas da temporada, comparada
          com a da liga.
        </LI>
        <LI>
          <Strong>Escreva a conclusão em uma frase.</Strong> Algo como: jogo equilibrado, com o
          mandante mais forte em casa e tendência de poucos gols. Se você não consegue resumir,
          a análise ainda não terminou.
        </LI>
      </OL>
      <Callout>
        O passo 7 é o que mais gente pula. Uma conclusão em uma frase obriga você a decidir o
        que os números mostraram, em vez de juntar dados sem fechar uma leitura.
      </Callout>

      <H2>Onde a análise costuma errar</H2>
      <P>
        Os erros mais comuns não são de conta, são de leitura. Dar peso demais ao último jogo,
        que ainda está fresco na memória. Confiar em amostra pequena como se fosse tendência.
        Ignorar que um time já classificado pode poupar titulares. E, principalmente, procurar
        nos números a confirmação de uma opinião que já existia antes de abrir a tela.
      </P>
      <P>
        Estatística não adivinha o placar. Ela mostra o que é mais provável e o quanto aquilo é
        mais provável, e futebol continua sendo um esporte em que o improvável acontece toda
        rodada.
      </P>

      <H2>Os dados reunidos numa tela só</H2>
      <P>
        Fazer esse roteiro à mão exige abrir várias abas: tabela, resultados de cada time,
        escalação, histórico do árbitro. O Raio-X do jogo do Pick IA junta tudo isso por
        partida: forma recente com os recortes de casa e fora, contra o G6 e na competição,
        confronto direto, escalação, classificação, estatística dos jogadores, perfil do árbitro
        na temporada e um resumo escrito pela IA.
      </P>
      <P>
        Para ver como os números de cada partida viram leitura, confira as{' '}
        <Link to="/palpites-de-futebol-hoje">análises dos jogos de hoje</Link>. Se você quer
        entender como julgar uma análise de outra pessoa, o texto sobre{' '}
        <Link to="/blog/como-avaliar-palpites-de-futebol">como avaliar palpites de futebol</Link>{' '}
        complementa este. E{' '}
        <Link to="/login?mode=register">criar uma conta</Link> libera dois dias de teste para
        abrir o Raio-X completo de qualquer jogo.
      </P>
      <Callout>
        Se você usa a análise para apostar, lembre que nenhum número elimina o risco. Aposte com
        responsabilidade. +18.
      </Callout>
    </>
  )
}
