/**
 * Raio-X do jogo no app (07/10/2026) · a aba Mercados do site.
 *
 * Mercado, de quem (os dois / mandante / visitante), tempo, linha: e a taxa
 * de acerto nos últimos jogos com uma barra por jogo e a odd da casa ao lado,
 * com o selo de valor. Escalação, tabela e o bilhete continuam no site por
 * enquanto · este é o recorte que mais se usa antes de apostar.
 */
import { useEffect, useMemo, useState } from 'react'
import { Linking, RefreshControl, ScrollView, View } from 'react-native'
import { Stack, useLocalSearchParams } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useDados } from '../../src/hooks/useDados'
import { jogos } from '../../src/api/endpoints'
import { Botao, Card, Carregando, Txt, Vazio } from '../../src/components/ui'
import { Barras, Chips, FormaPontos, LinhaDaOdd, NumeroDaTaxa, Passo, Segmento } from '../../src/components/raiox'
import {
  comPeriodo, MERCADOS_DE_TIME, MERCADOS_PRINCIPAIS, numero, resultadoDoJogo, ROTULO_PERIODO,
  rotuloDaLinha, taxa, type Lado, type Periodo, type RaioX,
} from '../../src/lib/raioX'
import { oddDaSelecao, type OddDaCasa } from '../../src/lib/oddsDoJogo'
import { cores, espaco } from '../../src/theme/tokens'
import { SITE_URL } from '../../src/config/env'

type Quem = 'jogo' | 'home' | 'away'

export default function RaioXDoJogo() {
  const p = useLocalSearchParams<{ id: string; home?: string; away?: string; league?: string; casa?: string; fora?: string }>()
  const fixtureId = Number(p.id)
  const insets = useSafeAreaInsets()
  const num = (v?: string) => (v ? Number(v) : undefined)

  const { dados, carregando, atualizando, erro, atualizar } = useDados<RaioX>(
    () => jogos.raioX(fixtureId, { home: num(p.home), away: num(p.away), league: num(p.league) }), [fixtureId])
  const [odds, setOdds] = useState<OddDaCasa[]>([])
  useEffect(() => { jogos.odds(fixtureId).then(setOdds).catch(() => {}) }, [fixtureId])

  const [principal, setPrincipal] = useState(MERCADOS_PRINCIPAIS[0].id)
  const [quem, setQuem] = useState<Quem>('jogo')
  const [periodoEscolhido, setPeriodo] = useState<Periodo>('total')
  const [lado, setLado] = useState<Lado>('mais')
  const [linhas, setLinhas] = useState<Record<string, number>>({})

  const par = MERCADOS_PRINCIPAIS.find((m) => m.id === principal)!
  const id = quem === 'jogo' ? par.jogo : par.time
  const mercado = MERCADOS_DE_TIME.find((m) => m.id === id)!
  const periodo: Periodo = mercado.soTotal ? 'total' : periodoEscolhido
  const chave = `${id}:${periodo}`
  const linha = linhas[chave] ?? (periodo === 'total' ? mercado.linhaPadrao : mercado.linhaPadraoTempo)

  const f = dados?.fixture
  const titulo = `${f?.home_team || p.casa || 'Casa'} x ${f?.away_team || p.fora || 'Fora'}`

  const quadros = useMemo(() => {
    if (!dados) return []
    const { home, away } = dados.times
    if (quem === 'jogo') {
      const vh = home.jogos.map((j) => numero(j, mercado.contador, 'jogo', periodo))
      const va = away.jogos.map((j) => numero(j, mercado.contador, 'jogo', periodo))
      return [
        { titulo: 'Nos jogos dos dois times', valores: [...vh, ...va], destaque: true },
        { titulo: dados.fixture.home_team, valores: vh },
        { titulo: dados.fixture.away_team, valores: va },
      ]
    }
    const ehCasa = quem === 'home'
    const time = ehCasa ? home : away, adv = ehCasa ? away : home
    const nome = ehCasa ? dados.fixture.home_team : dados.fixture.away_team
    const nomeAdv = ehCasa ? dados.fixture.away_team : dados.fixture.home_team
    const faz = time.jogos.map((j) => numero(j, mercado.contador, 'pro', periodo))
    const cede = adv.jogos.map((j) => numero(j, mercado.contador, 'contra', periodo))
    return [
      { titulo: `No confronto (${nome} faz + ${nomeAdv} cede)`, valores: [...faz, ...cede], destaque: true },
      { titulo: `${nome} faz`, valores: faz },
      { titulo: `${nomeAdv} cede`, valores: cede },
    ]
  }, [dados, quem, mercado.contador, periodo])

  const oddAtual = oddDaSelecao(odds, { mercado: id, quem, periodo, lado, linha })

  return (
    <>
      <Stack.Screen options={{ title: 'Raio-X do jogo' }} />
      {carregando ? (
        <Carregando texto="Montando o Raio-X" />
      ) : !dados ? (
        <Vazio titulo="Não foi possível carregar" descricao={erro ?? 'Tente de novo.'} />
      ) : (
        <ScrollView
          contentContainerStyle={{ paddingBottom: insets.bottom + espaco.xxl, gap: espaco.md }}
          refreshControl={<RefreshControl refreshing={atualizando} onRefresh={atualizar} tintColor={cores.ink3} />}
        >
          {/* placar */}
          <Card elevado style={{ margin: espaco.lg, marginBottom: 0, gap: espaco.md }}>
            <Txt variante="titulo" style={{ textAlign: 'center' }}>{titulo}</Txt>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <FormaPontos forma={dados.times.home.jogos.slice(0, 5).map(resultadoDoJogo).filter(Boolean) as string[]} />
              <Txt variante="apoio">{f?.match_datetime?.slice(11, 16) ?? ''}</Txt>
              <FormaPontos forma={dados.times.away.jogos.slice(0, 5).map(resultadoDoJogo).filter(Boolean) as string[]} />
            </View>
          </Card>

          <Chips opcoes={MERCADOS_PRINCIPAIS.map((m) => ({ id: m.id, rotulo: m.rotulo }))} valor={principal} onChange={setPrincipal} />

          <View style={{ paddingHorizontal: espaco.lg, gap: espaco.sm }}>
            <Segmento<Quem> valor={quem} onChange={setQuem} opcoes={[
              { id: 'jogo', rotulo: 'Os dois' },
              { id: 'home', rotulo: dados.fixture.home_team },
              { id: 'away', rotulo: dados.fixture.away_team },
            ]} />
            <Segmento<Periodo> valor={periodo} onChange={setPeriodo}
              desabilitar={(k) => !!mercado.soTotal && k !== 'total'}
              opcoes={(['total', '1t', '2t'] as Periodo[]).map((k) => ({ id: k, rotulo: ROTULO_PERIODO[k] }))} />
            <Segmento<Lado> valor={lado} onChange={setLado}
              opcoes={[{ id: 'mais', rotulo: 'Mais de' }, { id: 'menos', rotulo: 'Menos de' }]} />
            <Passo rotulo={rotuloDaLinha(linha, lado)} travaMenos={linha <= 0.5}
              onMenos={() => setLinhas((l) => ({ ...l, [chave]: Math.max(0.5, linha - 1) }))}
              onMais={() => setLinhas((l) => ({ ...l, [chave]: linha + 1 }))} />
          </View>

          {quadros.map((q) => {
            const t = taxa(q.valores, linha, lado)
            return (
              <Card key={q.titulo} style={{ marginHorizontal: espaco.lg, gap: espaco.md, borderColor: q.destaque ? cores.accent : cores.line }}>
                <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: espaco.md }}>
                  <View style={{ flex: 1 }}>
                    <Txt variante="corpo" cor={cores.ink1} style={{ fontWeight: '700' }}>{q.titulo}</Txt>
                    <Txt variante="apoio">{comPeriodo(mercado.frase, periodo)} · {rotuloDaLinha(linha, lado)}</Txt>
                  </View>
                  <NumeroDaTaxa t={t} grande={q.destaque} />
                </View>
                <Barras valores={q.valores} linha={linha} lado={lado} />
                {q.destaque ? <LinhaDaOdd odd={oddAtual} bateu={t.bateu} n={t.n} /> : null}
              </Card>
            )
          })}

          <View style={{ paddingHorizontal: espaco.lg }}>
            <Botao titulo="Jogadores, escalação, tabela e bilhete no site" variante="fantasma"
              onPress={() => Linking.openURL(`${SITE_URL}/jogos/${fixtureId}`)} />
          </View>
        </ScrollView>
      )}
    </>
  )
}
