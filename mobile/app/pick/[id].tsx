/**
 * Pick individual · também o destino dos deep links.
 *
 * Abre por `pickia://pick/123?tipo=vip` ou por link do site
 * (`https://pickia.com.br/pick/123`). O tipo diz de qual tabela o pick vem;
 * sem ele, assume VIP, que é o mesmo default do backend.
 *
 * Aqui cabe o que não coube no card: raciocínio do motor, EV, casa e stake
 * sugerido. É a mesma informação da web · o que muda é que no celular ela
 * fica atrás de um toque em vez de disputar espaço na lista.
 */
import { useLocalSearchParams } from 'expo-router'
import { Image, ScrollView, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Brain, Store } from 'lucide-react-native'
import { useDados } from '../../src/hooks/useDados'
import { aoVivo, picks as apiPicks } from '../../src/api/endpoints'
import { Card, Carregando, Dado, Selo, Separador, Txt, Vazio } from '../../src/components/ui'
import { cores, espaco } from '../../src/theme/tokens'
import {
  confianca,
  escudo,
  estiloDoResultado,
  ev,
  horaDoJogo,
  mercadoCompleto,
  odd,
  timeCasa,
  timeFora,
  unidades,
} from '../../src/lib/formato'
import type { PickAoVivo } from '../../src/api/types'

export default function DetalheDoPick() {
  const { id, tipo } = useLocalSearchParams<{ id: string; tipo?: string }>()
  const insets = useSafeAreaInsets()

  const pickId = Number(id)
  const origem = tipo ?? 'vip'
  const ehAoVivo = origem === 'live'

  const { dados, carregando, erro } = useDados<PickAoVivo>(
    () => (ehAoVivo ? aoVivo.detalhe(pickId) : apiPicks.detalhe(pickId, origem)) as Promise<PickAoVivo>,
    [pickId, origem],
  )

  if (carregando) return <Carregando texto="Carregando pick" />

  if (erro || !dados) {
    return (
      <View style={{ flex: 1, justifyContent: 'center' }}>
        <Vazio
          titulo="Pick indisponível"
          descricao={erro ?? 'Este pick não existe ou não está disponível para o seu plano.'}
        />
      </View>
    )
  }

  const resultado = estiloDoResultado(dados.result ?? null)
  const uriCasa = escudo(dados.home_team_id)
  const uriFora = escudo(dados.away_team_id)
  const hora = horaDoJogo(dados.match_datetime)

  return (
    <ScrollView
      contentContainerStyle={{ padding: espaco.lg, paddingBottom: insets.bottom + espaco.xxl, gap: espaco.lg }}
    >
      {/* confronto */}
      <Card style={{ gap: espaco.md }}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: espaco.sm }}>
          <Txt variante="apoio" numberOfLines={1} style={{ flex: 1 }}>
            {dados.league_name ?? 'Futebol'}
          </Txt>
          {ehAoVivo && dados.minute != null && !dados.result ? (
            <Selo texto={`${dados.minute}'`} cor={cores.red} />
          ) : hora ? (
            <Txt variante="apoio">{hora}</Txt>
          ) : null}
        </View>

        <View style={{ gap: espaco.sm }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
            {uriCasa ? <Image source={{ uri: uriCasa }} style={{ width: 22, height: 22 }} resizeMode="contain" /> : null}
            <Txt variante="corpo" style={{ flex: 1, color: cores.ink1 }}>{timeCasa(dados)}</Txt>
            {ehAoVivo ? <Txt variante="numero">{dados.home_goals ?? dados.home_goals_at_creation ?? 0}</Txt> : null}
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
            {uriFora ? <Image source={{ uri: uriFora }} style={{ width: 22, height: 22 }} resizeMode="contain" /> : null}
            <Txt variante="corpo" style={{ flex: 1, color: cores.ink1 }}>{timeFora(dados)}</Txt>
            {ehAoVivo ? <Txt variante="numero">{dados.away_goals ?? dados.away_goals_at_creation ?? 0}</Txt> : null}
          </View>
        </View>
      </Card>

      {/* a recomendação */}
      <Card elevado style={{ gap: espaco.lg }}>
        <View style={{ gap: espaco.xs }}>
          <Txt variante="rotulo">Recomendação do motor</Txt>
          <Txt variante="titulo">{mercadoCompleto(dados.market, dados.line)}</Txt>
        </View>

        <Separador />

        <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          <Dado rotulo="Odd" valor={odd(dados.odd)} cor={cores.accent} />
          <Dado rotulo="Confiança" valor={confianca(dados.confidence)} />
          <Dado rotulo="EV" valor={ev(dados.ev)} />
          <Dado rotulo="Situação" valor={resultado.rotulo} cor={resultado.cor} />
        </View>

        {dados.stake_units != null || dados.stake_pct != null ? (
          <>
            <Separador />
            <Dado
              rotulo="Stake sugerido"
              valor={dados.stake_units != null ? unidades(dados.stake_units) : `${dados.stake_pct}% da banca`}
            />
          </>
        ) : null}

        {dados.bet_house ? (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
            <Store size={14} color={cores.ink3} />
            <Txt variante="apoio">Odd observada em {dados.bet_house}</Txt>
          </View>
        ) : null}
      </Card>

      {/* raciocínio · texto que o motor gravou junto com o pick */}
      {dados.reasoning ? (
        <Card style={{ gap: espaco.md }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
            <Brain size={16} color={cores.accent} />
            <Txt variante="rotulo">Por que este pick</Txt>
          </View>
          <Txt variante="corpo" style={{ lineHeight: 22 }}>
            {dados.reasoning}
          </Txt>
        </Card>
      ) : null}

      {/* contexto ao vivo · o que o motor via no momento em que criou */}
      {ehAoVivo ? (
        <Card style={{ gap: espaco.md }}>
          <Txt variante="rotulo">No momento da criação</Txt>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', flexWrap: 'wrap', gap: espaco.lg }}>
            {dados.minute_at_creation != null ? (
              <Dado rotulo="Minuto" valor={`${dados.minute_at_creation}'`} />
            ) : null}
            {dados.remaining_minutes != null ? (
              <Dado rotulo="Restavam" valor={`${dados.remaining_minutes} min`} />
            ) : null}
            {dados.odd_at_creation != null ? (
              <Dado rotulo="Odd inicial" valor={odd(dados.odd_at_creation)} />
            ) : null}
            {dados.stat_label && dados.stat_value != null ? (
              <Dado rotulo={dados.stat_label} valor={String(dados.stat_value)} />
            ) : null}
          </View>
        </Card>
      ) : null}
    </ScrollView>
  )
}
