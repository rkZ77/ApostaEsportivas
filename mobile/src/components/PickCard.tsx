/**
 * Card de pick pré-jogo.
 *
 * Adaptação mobile do card do site: a tela do celular não comporta o mesmo
 * tanto de informação, então aqui ficam só os campos que decidem a aposta --
 * confronto, mercado, odd e confiança. Raciocínio, EV, casa e forma do
 * mercado continuam existindo e aparecem ao abrir o pick. Nenhum número é
 * recalculado: tudo vem do motor como está.
 */
import { Image, View } from 'react-native'
import { Card, Selo, Txt } from './ui'
import { cores, espaco } from '../theme/tokens'
import { confianca, escudo, estiloDoResultado, horaDoJogo, mercadoCompleto, odd, timeCasa, timeFora } from '../lib/formato'
import type { Pick } from '../api/types'

function Escudo({ id }: { id?: number | null }) {
  const uri = escudo(id)
  if (!uri) return <View style={{ width: 20, height: 20 }} />
  return <Image source={{ uri }} style={{ width: 20, height: 20 }} resizeMode="contain" />
}

export function PickCard({ pick, onPress }: { pick: Pick; onPress?: () => void }) {
  const resultado = estiloDoResultado(pick.result ?? null)
  const hora = horaDoJogo(pick.match_datetime)

  return (
    <Card onPress={onPress} style={{ gap: espaco.md }}>
      {/* cabeçalho: liga e horário, o contexto mínimo */}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: espaco.sm }}>
        <Txt variante="apoio" numberOfLines={1} style={{ flex: 1 }}>
          {pick.league_name ?? 'Futebol'}
        </Txt>
        {hora ? <Txt variante="apoio">{hora}</Txt> : null}
      </View>

      {/* confronto: um time por linha, que é como se lê placar no celular */}
      <View style={{ gap: espaco.sm }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
          <Escudo id={pick.home_team_id} />
          <Txt variante="corpo" numberOfLines={1} style={{ flex: 1, color: cores.ink1 }}>
            {timeCasa(pick)}
          </Txt>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
          <Escudo id={pick.away_team_id} />
          <Txt variante="corpo" numberOfLines={1} style={{ flex: 1, color: cores.ink1 }}>
            {timeFora(pick)}
          </Txt>
        </View>
      </View>

      {/* a aposta em si */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: espaco.md,
          borderTopWidth: 1,
          borderTopColor: cores.line,
          paddingTop: espaco.md,
        }}
      >
        <View style={{ flex: 1, gap: 2 }}>
          <Txt variante="rotulo">Mercado</Txt>
          <Txt variante="corpo" numberOfLines={2} style={{ color: cores.ink1 }}>
            {mercadoCompleto(pick.market, pick.line)}
          </Txt>
        </View>
        <View style={{ alignItems: 'flex-end', gap: 2 }}>
          <Txt variante="rotulo">Odd</Txt>
          <Txt variante="numero" cor={cores.accent}>
            {odd(pick.odd)}
          </Txt>
        </View>
      </View>

      {/* rodapé: confiança e situação */}
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: espaco.sm }}>
        <Txt variante="apoio">Confiança {confianca(pick.confidence)}</Txt>
        <View style={{ flexDirection: 'row', gap: espaco.sm, alignItems: 'center' }}>
          {pick.is_followed ? <Selo texto="Seguindo" cor={cores.blue} /> : null}
          <Selo texto={resultado.rotulo} cor={resultado.cor} preenchido={Boolean(pick.result)} />
        </View>
      </View>
    </Card>
  )
}
