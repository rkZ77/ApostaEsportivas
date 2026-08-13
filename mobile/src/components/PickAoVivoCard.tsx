/**
 * Card de pick ao vivo · a tela de maior prioridade do app.
 *
 * O usuário está com o jogo rolando e precisa decidir em segundos. Por isso
 * a hierarquia aqui é diferente da do pré-jogo: minuto e placar primeiro,
 * depois a aposta, e a validade da odd em destaque -- é a informação que
 * perde valor mais rápido. Tudo que não ajuda a decidir agora fica fora e
 * aparece só ao abrir o pick.
 */
import { useEffect, useState } from 'react'
import { Image, Text, View } from 'react-native'
import { Card, Selo, Txt } from './ui'
import { cores, espaco, fonte, peso, raio } from '../theme/tokens'
import { confianca, escudo, estiloDoResultado, mercadoCompleto, odd, timeCasa, timeFora } from '../lib/formato'
import type { PickAoVivo } from '../api/types'

function Escudo({ id }: { id?: number | null }) {
  const uri = escudo(id)
  if (!uri) return <View style={{ width: 22, height: 22 }} />
  return <Image source={{ uri }} style={{ width: 22, height: 22 }} resizeMode="contain" />
}

/**
 * Contagem regressiva da validade da odd.
 *
 * Roda no cliente, a partir dos segundos que o backend mandou. É só
 * apresentação: quem decide se o pick ainda vale é o servidor, na próxima
 * atualização do feed. Sem isso, o usuário olharia uma odd já vencida sem
 * perceber.
 */
function Validade({ segundos }: { segundos: number }) {
  const [restante, setRestante] = useState(segundos)

  useEffect(() => {
    setRestante(segundos)
    if (segundos <= 0) return
    const id = setInterval(() => setRestante((s) => (s > 0 ? s - 1 : 0)), 1000)
    return () => clearInterval(id)
  }, [segundos])

  if (restante <= 0) return <Selo texto="Odd vencida" cor={cores.ink4} />

  const min = Math.floor(restante / 60)
  const seg = restante % 60
  const urgente = restante < 60

  return (
    <Selo
      texto={`Vale por ${min}:${String(seg).padStart(2, '0')}`}
      cor={urgente ? cores.amber : cores.ink3}
    />
  )
}

export function PickAoVivoCard({ pick, onPress }: { pick: PickAoVivo; onPress?: () => void }) {
  const resultado = estiloDoResultado(pick.result ?? null)
  const encerrado = Boolean(pick.result) || pick.is_ft
  const minuto = pick.minute ?? pick.minute_at_creation

  return (
    <Card onPress={onPress} style={{ gap: espaco.md, opacity: encerrado ? 0.72 : 1 }}>
      {/* estado da partida · o que o usuário procura primeiro */}
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: espaco.sm }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm, flex: 1 }}>
          {pick.is_live && !encerrado ? (
            <View style={{ width: 7, height: 7, borderRadius: raio.pill, backgroundColor: cores.red }} />
          ) : null}
          <Txt variante="apoio" numberOfLines={1} style={{ flex: 1 }}>
            {pick.league_name ?? 'Ao vivo'}
          </Txt>
        </View>
        {minuto != null ? (
          <Txt variante="apoio" cor={encerrado ? cores.ink3 : cores.ink1}>
            {encerrado ? 'Encerrado' : `${minuto}'`}
          </Txt>
        ) : null}
      </View>

      {/* placar · um time por linha, com o gol à direita */}
      <View style={{ gap: espaco.sm }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
          <Escudo id={pick.home_team_id} />
          <Txt variante="corpo" numberOfLines={1} style={{ flex: 1, color: cores.ink1 }}>
            {timeCasa(pick)}
          </Txt>
          <Text style={{ fontSize: fonte.lg, fontWeight: peso.bold, color: cores.ink1, fontVariant: ['tabular-nums'] }}>
            {pick.home_goals ?? pick.home_goals_at_creation ?? 0}
          </Text>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
          <Escudo id={pick.away_team_id} />
          <Txt variante="corpo" numberOfLines={1} style={{ flex: 1, color: cores.ink1 }}>
            {timeFora(pick)}
          </Txt>
          <Text style={{ fontSize: fonte.lg, fontWeight: peso.bold, color: cores.ink1, fontVariant: ['tabular-nums'] }}>
            {pick.away_goals ?? pick.away_goals_at_creation ?? 0}
          </Text>
        </View>
      </View>

      {/* a aposta */}
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

      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: espaco.sm }}>
        <Txt variante="apoio">Confiança {confianca(pick.confidence)}</Txt>
        <View style={{ flexDirection: 'row', gap: espaco.sm, alignItems: 'center' }}>
          {encerrado ? (
            <Selo texto={resultado.rotulo} cor={resultado.cor} preenchido={Boolean(pick.result)} />
          ) : pick.segundos_de_validade != null ? (
            <Validade segundos={pick.segundos_de_validade} />
          ) : null}
        </View>
      </View>
    </Card>
  )
}
