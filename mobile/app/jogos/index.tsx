/**
 * Jogos do dia · a porta do Raio-X no app (07/10/2026).
 *
 * Só as ligas cadastradas (o backend já recorta), agrupadas por liga, com a
 * forma recente dos dois times. Tocar no jogo abre o Raio-X. É tela da pilha,
 * e não aba: a barra inferior tem cinco abas, que é o teto pro polegar.
 */
import { useMemo, useState } from 'react'
import { Pressable, RefreshControl, SectionList, TextInput, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { CalendarDays } from 'lucide-react-native'
import { useDados } from '../../src/hooks/useDados'
import { jogos, type JogoDoDia } from '../../src/api/endpoints'
import { Carregando, Txt, Vazio } from '../../src/components/ui'
import { FormaPontos } from '../../src/components/raiox'
import { cores, espaco, familia, fonte, peso, raio } from '../../src/theme/tokens'

const AO_VIVO = new Set(['1H', 'HT', '2H', 'ET', 'BT', 'P', 'LIVE', 'INT', 'SUSP'])
const FIM = new Set(['FT', 'AET', 'PEN'])

const semAcento = (t: string) => t.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

export default function Jogos() {
  const router = useRouter()
  const insets = useSafeAreaInsets()
  const [busca, setBusca] = useState('')
  const { dados, carregando, atualizando, erro, atualizar } = useDados(() => jogos.doDia(), [], { intervaloMs: 60_000 })

  const secoes = useMemo(() => {
    const termo = semAcento(busca.trim())
    const visiveis = (dados ?? []).filter((j) =>
      !termo || semAcento(`${j.home_team} ${j.away_team} ${j.league_name}`).includes(termo))
    const porLiga = new Map<string, JogoDoDia[]>()
    for (const j of visiveis) porLiga.set(j.league_name, [...(porLiga.get(j.league_name) ?? []), j])
    return [...porLiga].map(([title, data]) => ({ title, data }))
  }, [dados, busca])

  const abrir = (j: JogoDoDia) => {
    const q = new URLSearchParams()
    if (j.home_team_id) q.set('home', String(j.home_team_id))
    if (j.away_team_id) q.set('away', String(j.away_team_id))
    q.set('league', String(j.league_id))
    q.set('casa', j.home_team)
    q.set('fora', j.away_team)
    router.push(`/jogos/${j.fixture_id}?${q.toString()}`)
  }

  if (carregando) return <Carregando texto="Carregando os jogos de hoje" />

  return (
    <SectionList
      sections={secoes}
      keyExtractor={(j) => String(j.fixture_id)}
      stickySectionHeadersEnabled
      contentContainerStyle={{ paddingBottom: insets.bottom + espaco.xxl, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={atualizando} onRefresh={atualizar} tintColor={cores.ink3} />}
      ListHeaderComponent={
        <View style={{ padding: espaco.lg, paddingBottom: espaco.sm }}>
          <TextInput
            value={busca}
            onChangeText={setBusca}
            placeholder="Buscar time ou liga"
            placeholderTextColor={cores.ink4}
            style={{
              minHeight: 46, borderRadius: raio.md, paddingHorizontal: espaco.lg,
              backgroundColor: cores.surface2, color: cores.ink1, fontSize: fonte.base, fontFamily: familia(peso.normal),
            }}
          />
        </View>
      }
      renderSectionHeader={({ section }) => (
        <View style={{ backgroundColor: cores.surface0, paddingHorizontal: espaco.lg, paddingVertical: espaco.sm }}>
          <Txt variante="rotulo">{section.title}</Txt>
        </View>
      )}
      renderItem={({ item: j }) => {
        const vivo = AO_VIVO.has(j.status)
        const fim = FIM.has(j.status)
        const hora = j.match_datetime?.slice(11, 16) ?? '--:--'
        return (
          <Pressable
            onPress={() => abrir(j)}
            style={({ pressed }) => ({
              flexDirection: 'row', alignItems: 'center', gap: espaco.md,
              paddingHorizontal: espaco.lg, paddingVertical: espaco.md,
              backgroundColor: pressed ? cores.surface2 : cores.surface1,
              borderBottomWidth: 1, borderBottomColor: cores.line,
              borderLeftWidth: j.has_pick ? 3 : 0, borderLeftColor: cores.accent,
            })}
          >
            <View style={{ width: 48 }}>
              <Txt variante="apoio" cor={vivo ? cores.accent : fim ? cores.ink4 : cores.ink2}
                style={{ fontWeight: '700' }}>
                {vivo ? `${j.elapsed ?? ''}'` : fim ? 'Fim' : hora}
              </Txt>
            </View>
            <View style={{ flex: 1, gap: 6 }}>
              {([
                [j.home_team, j.home_goals, j.forma_home],
                [j.away_team, j.away_goals, j.forma_away],
              ] as const).map(([nome, gols, forma]) => (
                <View key={nome} style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
                  <Txt variante="corpo" cor={cores.ink1} numberOfLines={1} style={{ flex: 1, fontWeight: '600' }}>{nome}</Txt>
                  {vivo || fim ? (
                    <Txt variante="numero" cor={vivo ? cores.accent : cores.ink1}>{String(gols ?? 0)}</Txt>
                  ) : forma?.length ? <FormaPontos forma={forma} pequeno /> : null}
                </View>
              ))}
            </View>
          </Pressable>
        )
      }}
      ListEmptyComponent={
        <Vazio
          icone={<CalendarDays size={32} color={cores.ink4} />}
          titulo={erro ? 'Não foi possível carregar' : 'Nenhum jogo hoje nas nossas ligas'}
          descricao={erro ?? 'Data FIFA e intervalo de temporada deixam a agenda vazia. Puxe para atualizar.'}
        />
      }
    />
  )
}
