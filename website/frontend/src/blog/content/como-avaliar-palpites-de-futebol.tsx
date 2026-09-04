import { Link } from 'react-router-dom'
import { P, H2, H3, UL, OL, LI, Strong, Callout } from '../article-ui'

export default function ComoAvaliarPalpitesDeFutebol() {
  return (
    <>
      <P>
        Existem <Strong>palpites de futebol</Strong> em todo canto: grupo de WhatsApp, perfil no
        Instagram, canal no Telegram, site de estatística. O problema é que quase nenhum deles
        mostra o que aconteceu depois. Você vê o palpite antes do jogo e nunca mais ouve falar
        dele se ele der errado. Este texto é sobre o que olhar antes de colocar dinheiro em um
        palpite, seja ele seu, de um tipster ou de um modelo estatístico.
      </P>

      <H2>Um palpite de futebol não é uma previsão, é um preço</H2>
      <P>
        A primeira confusão que custa dinheiro é achar que o objetivo de um palpite é acertar.
        Não é. O objetivo é encontrar uma aposta em que a casa está pagando mais do que o risco
        real justifica. Um palpite que acerta 70% das vezes numa odd de 1.30 perde dinheiro no
        longo prazo. Um que acerta 40% numa odd de 3.00 ganha.
      </P>
      <P>
        A conta que separa os dois é o valor esperado. Multiplique a probabilidade de acerto
        pelo lucro da odd e subtraia a probabilidade de erro. Com 40% de chance numa odd 3.00:
        0,40 vezes 2,00 dá 0,80, menos 0,60 de erro, resulta em 0,20. Cada real apostado devolve
        vinte centavos de expectativa positiva. Com 70% numa odd 1.30: 0,70 vezes 0,30 dá 0,21,
        menos 0,30, resulta em uma perda esperada de nove centavos por real.
      </P>
      <Callout>
        Acerto alto e lucro são coisas diferentes. Antes de comparar dois palpites pelo número
        de greens, compare pela odd em que cada um saiu.
      </Callout>

      <H2>Como avaliar palpites de futebol: as 7 perguntas</H2>
      <P>
        Este é o checklist prático. Se um palpite não responde a maioria delas, o problema não é
        ele estar errado, é você não ter como saber.
      </P>
      <OL>
        <LI>
          <Strong>Qual é a odd e onde ela foi pega?</Strong> Palpite sem odd registrada não pode
          ser avaliado depois. A odd muda ao longo do dia, e "eu peguei 2.10" dito depois do jogo
          não vale nada.
        </LI>
        <LI>
          <Strong>Qual é o mercado exato?</Strong> "Vitória do time da casa" é claro. "Jogo com
          gols" não é. Linha, lado e mercado precisam estar escritos antes do apito.
        </LI>
        <LI>
          <Strong>De quantos jogos veio a estatística?</Strong> Média de escanteios de três jogos
          não descreve nada. A regra prática é olhar com desconfiança qualquer número tirado de
          menos de dez partidas.
        </LI>
        <LI>
          <Strong>A amostra é comparável?</Strong> Média de gols de um time somando jogos da
          liga, da copa nacional e de amistoso mistura contextos diferentes. Mata-mata e pontos
          corridos produzem jogos diferentes.
        </LI>
        <LI>
          <Strong>Existe histórico público de quem publicou?</Strong> Não o print da última
          semana, o histórico inteiro, com os erros dentro.
        </LI>
        <LI>
          <Strong>O tamanho da entrada foi definido antes?</Strong> Palpite sem stake é meia
          informação. Quem decide o valor no impulso do momento transforma um bom palpite em
          gestão ruim, e o que quebra a banca é a segunda coisa.
        </LI>
        <LI>
          <Strong>O que precisaria acontecer para o palpite estar errado?</Strong> Se a resposta
          não existe, você não está diante de uma análise, está diante de uma opinião.
        </LI>
      </OL>

      <H2>Os três sinais de alerta mais comuns</H2>
      <H3>Histórico que começa na semana passada</H3>
      <P>
        Um mês bom acontece por acaso com frequência muito maior do que as pessoas imaginam.
        Sequência curta de acertos é o resultado mais fácil de produzir e o mais fácil de
        selecionar depois. Se o histórico apresentado tem começo recente ou pula períodos,
        assuma que os períodos que faltam foram ruins.
      </P>
      <H3>Odd alta apresentada como qualidade</H3>
      <P>
        Odd de 4.00 não é um palpite melhor, é um palpite com menos chance de acontecer. Odd
        muito acima do que o mercado paga em jogos parecidos costuma significar que a casa sabe
        de algo que a análise não considerou, como desfalque, time reserva ou jogo sem
        importância na tabela.
      </P>
      <H3>Palpite que muda de versão depois do jogo</H3>
      <P>
        "Eu falei que ia ser jogo truncado" não é o mesmo que ter publicado menos de 2.5 gols
        antes da bola rolar. Registro anterior ao apito, com odd e mercado, é o que separa
        análise de narrativa.
      </P>

      <H2>Como usar estatística sem se enganar com ela</H2>
      <P>
        Estatística de futebol descreve o passado, e o passado só serve quando as condições se
        repetem. Alguns cuidados que mudam bastante a qualidade da leitura:
      </P>
      <UL>
        <LI>
          Separe casa e fora. Muitos times têm perfil de jogo completamente diferente jogando em
          casa, principalmente em número de faltas e escanteios.
        </LI>
        <LI>
          Prefira mediana a média quando houver um jogo atípico na amostra. Uma goleada de 6 a 0
          distorce a média de gols de dez partidas.
        </LI>
        <LI>
          Confira se o dado é do time ou da partida. "Média de 5,2 escanteios" significa coisas
          diferentes se for do time ou do jogo inteiro.
        </LI>
        <LI>
          Desconfie de dado sem fonte de coleta. Provedores diferentes contam falta e chute no
          alvo com critérios diferentes.
        </LI>
      </UL>
      <P>
        Se você quer entender a parte de quanto apostar em cada entrada, o caminho seguinte é o{' '}
        <Link to="/blog/kelly-criterion-apostas-esportivas">Kelly Criterion</Link>, que calcula
        a fração da banca por aposta a partir da probabilidade e da odd.
      </P>

      <H2>O que fazer com o checklist na prática</H2>
      <P>
        Guarde as sete perguntas e aplique nos próximos dez palpites que você receber, sem
        apostar. O objetivo não é achar o palpite perfeito, é perceber quantos deles não passam
        nem da primeira pergunta. Depois disso, a escolha de onde colocar dinheiro fica bem mais
        simples.
      </P>
      <P>
        No Pick IA todo palpite nasce com mercado, linha, odd e o tamanho da entrada definidos
        antes do jogo, e todos ficam registrados em público depois, acerto e erro. Dá para
        conferir os{' '}
        <Link to="/palpites-de-futebol-hoje">palpites de futebol de hoje</Link> e o{' '}
        <Link to="/resultados">histórico completo</Link> sem ter conta, e{' '}
        <Link to="/login?mode=register">criar uma conta</Link> libera dois dias de VIP para
        testar a análise por dentro.
      </P>
      <Callout>
        Nenhum método elimina o risco. Aposta esportiva envolve variância, e sequência ruim
        acontece mesmo com decisões corretas. Aposte apenas o que você pode perder, e trate
        gestão de banca como parte da estratégia, não como detalhe.
      </Callout>
    </>
  )
}
