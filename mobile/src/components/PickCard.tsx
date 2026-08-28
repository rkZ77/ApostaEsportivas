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
import { confianca, escudo, estiloDoResultado, horaDoJogo, mercadoCompleto, odd, reais, timeCasa, timeFora } from '../lib/formato'
import type { Banca, Pick } from '../api/types'

function Escudo({ id }: { id?: number | null }) {
  const uri = escudo(id)
  if (!uri) return <View style={{ width: 20, height: 20 }} />
  return <Image source={{ uri }} style={{ width: 20, height: 20 }} resizeMode="contain" />
}

/** O que o card precisa da banca · o resumo inteiro seria acoplamento à toa. */
export interface BancaDoCard {
  bankroll_current?: number | null
  unit_value?: number | null
}

export function PickCard({ pick, onPress, banca }: {
  pick: Pick
  onPress?: () => void
  banca?: BancaDoCard | null
}) {
  const resultado = estiloDoResultado(pick.result ?? null)
  const hora = horaDoJogo(pick.match_datetime)

  /* QUANTAS UNIDADES, E QUANTO ISSO É EM REAIS.
   *
   * Faltava no app inteiro · o card mostrava mercado, odd e confiança, e parava
   * aí. O usuário tinha o pick e não tinha a aposta: a unidade é o que traduz
   * "78% e odd 1.72" numa decisão, e sem ela ele voltava pro site pra descobrir.
   *
   * O NÚMERO É DO BACKEND, não recalculado aqui. `suggested_stake_units` sai de
   * `calculate_stake` com a banca real do usuário, e é o mesmo campo que o card
   * do site usa como primeira opção. Portar o Kelly pro app criaria uma segunda
   * implementação da mesma conta, e as duas divergiriam no primeiro ajuste ·
   * é o erro que o projeto já pagou com `stakePlan` e resolveu com um teste
   * comparando os dois lados.
   *
   * Quem já apostou vê o que APOSTOU, não o que era sugerido. */
  const unidades = pick.user_stake_units ?? pick.suggested_stake_units ?? null
  const valorDaUnidade = banca?.unit_value ?? null
  const jaApostou = pick.user_stake_units != null

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

      {/* quanto apostar · só enquanto a aposta ainda existe. Num pick já
          resolvido a unidade sugerida vira ruído: a decisão passou. */}
      {unidades != null && !pick.result ? (
        <View
          style={{
            flexDirection: 'row',
            justifyContent: 'space-between',
            alignItems: 'flex-end',
            gap: espaco.md,
            borderTopWidth: 1,
            borderTopColor: cores.line,
            paddingTop: espaco.md,
          }}
        >
          <View style={{ gap: 2 }}>
            <Txt variante="rotulo">{jaApostou ? 'Apostado' : 'Apostar'}</Txt>
            <Txt variante="numero" cor={cores.green}>{unidades}u</Txt>
            {valorDaUnidade ? (
              <Txt variante="apoio">{reais(unidades * valorDaUnidade)}</Txt>
            ) : null}
          </View>
          <View style={{ alignItems: 'flex-end', gap: 2 }}>
            <Txt variante="rotulo">Lucro pot.</Txt>
            <Txt variante="numero" cor={cores.ink1}>
              +{((Number(pick.odd) - 1) * unidades).toFixed(2)}u
            </Txt>
            {valorDaUnidade ? (
              <Txt variante="apoio">
                +{reais((Number(pick.odd) - 1) * unidades * valorDaUnidade)}
              </Txt>
            ) : null}
          </View>
        </View>
      ) : null}

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
