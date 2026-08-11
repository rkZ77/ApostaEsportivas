/**
 * Picks pré-jogo do dia, com filtro por tipo.
 *
 * Os tipos (VIP, dica gratuita, faltas, defesas) já vêm separados por
 * `/suggestions/today` -- aqui eles só viram abas de filtro, porque no
 * celular não cabe mostrar as quatro listas empilhadas de uma vez. Quem
 * decide o que cada plano enxerga continua sendo o backend.
 */
import { useMemo, useState } from 'react'
import { FlatList, Pressable, RefreshControl, ScrollView, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Target } from 'lucide-react-native'
import { useDados } from '../../src/hooks/useDados'
import { picks as apiPicks } from '../../src/api/endpoints'
import { Carregando, Txt, Vazio } from '../../src/components/ui'
import { PickCard } from '../../src/components/PickCard'
import { cores, espaco, raio } from '../../src/theme/tokens'
import type { Pick } from '../../src/api/types'

type Filtro = 'todos' | 'vip' | 'gratuito' | 'faltas' | 'goleiros'

const FILTROS: { chave: Filtro; rotulo: string }[] = [
  { chave: 'todos', rotulo: 'Todos' },
  { chave: 'vip', rotulo: 'VIP' },
  { chave: 'gratuito', rotulo: 'Gratuito' },
  { chave: 'faltas', rotulo: 'Faltas' },
  { chave: 'goleiros', rotulo: 'Defesas' },
]

export default function Picks() {
  const router = useRouter()
  const insets = useSafeAreaInsets()
  const [filtro, setFiltro] = useState<Filtro>('todos')

  const { dados, carregando, atualizando, erro, atualizar } = useDados(() => apiPicks.hoje(), [])

  /* Cada tipo carrega o rótulo de origem porque a rota de detalhe precisa
     saber de qual tabela o pick veio. */
  const lista = useMemo(() => {
    if (!dados) return [] as (Pick & { origem: string })[]
    const marcar = (arr: Pick[] | undefined, origem: string) =>
      (arr ?? []).map((p) => ({ ...p, origem }))

    const vip = marcar(dados.vip, 'vip')
    const gratuito = dados.dica_do_dia ? marcar([dados.dica_do_dia], 'free') : []
    const faltas = marcar(dados.faltas, 'faltas')
    const goleiros = marcar(dados.goleiros, 'goleiros')

    if (filtro === 'vip') return vip
    if (filtro === 'gratuito') return gratuito
    if (filtro === 'faltas') return faltas
    if (filtro === 'goleiros') return goleiros
    return [...gratuito, ...vip, ...faltas, ...goleiros]
  }, [dados, filtro])

  return (
    <View style={{ flex: 1 }}>
      {/* filtros · rolagem horizontal para caber sem apertar os alvos de toque */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: espaco.lg, paddingVertical: espaco.md, gap: espaco.sm }}
        style={{ flexGrow: 0 }}
      >
        {FILTROS.map(({ chave, rotulo }) => {
          const ativo = filtro === chave
          return (
            <Pressable
              key={chave}
              onPress={() => setFiltro(chave)}
              style={{
                paddingHorizontal: espaco.lg,
                paddingVertical: espaco.sm,
                borderRadius: raio.pill,
                backgroundColor: ativo ? cores.accent : cores.surface2,
                minHeight: 38,
                justifyContent: 'center',
              }}
            >
              <Txt variante="apoio" cor={ativo ? cores.surface0 : cores.ink2} style={{ fontWeight: '600' }}>
                {rotulo}
              </Txt>
            </Pressable>
          )
        })}
      </ScrollView>

      {carregando ? (
        <Carregando texto="Carregando picks do dia" />
      ) : (
        <FlatList
          data={lista}
          keyExtractor={(item) => `${item.origem}-${item.id}`}
          contentContainerStyle={{
            paddingHorizontal: espaco.lg,
            paddingBottom: insets.bottom + espaco.xxl,
            gap: espaco.md,
            flexGrow: 1,
          }}
          refreshControl={<RefreshControl refreshing={atualizando} onRefresh={atualizar} tintColor={cores.ink3} />}
          renderItem={({ item }) => (
            <PickCard pick={item} onPress={() => router.push(`/pick/${item.id}?tipo=${item.origem}`)} />
          )}
          ListEmptyComponent={
            <Vazio
              icone={<Target size={32} color={cores.ink4} />}
              titulo={erro ? 'Não foi possível carregar' : 'Nenhum pick nesta seleção'}
              descricao={
                erro ??
                'Os picks saem quando o motor encontra valor real na partida. Puxe para atualizar.'
              }
            />
          }
        />
      )}
    </View>
  )
}
