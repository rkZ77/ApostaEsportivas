/**
 * Picks ao vivo · a tela prioritária.
 *
 * Atualização: 20 segundos, e só com a tela em foco e o app em primeiro
 * plano (ver useDados). O número não é chutado -- o motor Live trabalha em
 * janelas de minuto da partida, então atualizar mais rápido que isso gasta
 * bateria e cota sem trazer informação nova, e mais devagar deixa passar
 * odd vencendo. A atualização é silenciosa: a lista não pisca nem volta ao
 * topo enquanto o usuário lê.
 */
import { useMemo } from 'react'
import { FlatList, RefreshControl, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Activity, Lock } from 'lucide-react-native'
import { useAuth } from '../../src/auth/AuthContext'
import { useDados } from '../../src/hooks/useDados'
import { aoVivo } from '../../src/api/endpoints'
import { Carregando, Selo, Txt, Vazio } from '../../src/components/ui'
import { PickAoVivoCard } from '../../src/components/PickAoVivoCard'
import { cores, espaco } from '../../src/theme/tokens'

const INTERVALO_MS = 20000

export default function AoVivo() {
  const router = useRouter()
  const insets = useSafeAreaInsets()
  const { isVip } = useAuth()

  const { dados, carregando, atualizando, erro, atualizar } = useDados(
    () => aoVivo.feed(30, true),
    [],
    { intervaloMs: INTERVALO_MS, habilitado: isVip },
  )

  /* Em aberto primeiro; encerrados descem. Quem está acompanhando um jogo
     quer ver o que ainda dá para apostar, não o histórico do dia. */
  const lista = useMemo(() => {
    const picks = dados?.picks ?? []
    return [...picks].sort((a, b) => Number(Boolean(a.result)) - Number(Boolean(b.result)))
  }, [dados])

  const emAberto = lista.filter((p) => !p.result).length

  if (!isVip) {
    return (
      <View style={{ flex: 1, justifyContent: 'center' }}>
        <Vazio
          icone={<Lock size={32} color={cores.ink4} />}
          titulo="Ao vivo é exclusivo do VIP"
          descricao="O motor Live acompanha as partidas em andamento e publica oportunidades com a odd ainda válida. Disponível no plano VIP."
        />
      </View>
    )
  }

  if (carregando) return <Carregando texto="Buscando oportunidades ao vivo" />

  // O backend responde `disponivel: false` quando o motor Live não rodou
  // neste ambiente · é um estado normal em DEV, não um erro.
  if (dados && !dados.disponivel) {
    return (
      <View style={{ flex: 1, justifyContent: 'center' }}>
        <Vazio
          icone={<Activity size={32} color={cores.ink4} />}
          titulo="Motor Live sem dados aqui"
          descricao={dados.motivo ?? 'O motor Live ainda não rodou neste ambiente.'}
        />
      </View>
    )
  }

  return (
    <View style={{ flex: 1 }}>
      {/* barra de estado · confirma que a tela está viva sem poluir os cards */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingHorizontal: espaco.lg,
          paddingVertical: espaco.md,
          gap: espaco.sm,
        }}
      >
        <Txt variante="apoio">
          {emAberto === 0
            ? 'Nenhuma oportunidade aberta'
            : emAberto === 1
              ? '1 oportunidade aberta'
              : `${emAberto} oportunidades abertas`}
        </Txt>
        <Selo texto="Atualiza sozinho" cor={cores.ink4} />
      </View>

      <FlatList
        data={lista}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{
          paddingHorizontal: espaco.lg,
          paddingBottom: insets.bottom + espaco.xxl,
          gap: espaco.md,
          flexGrow: 1,
        }}
        refreshControl={<RefreshControl refreshing={atualizando} onRefresh={atualizar} tintColor={cores.ink3} />}
        renderItem={({ item }) => (
          <PickAoVivoCard pick={item} onPress={() => router.push(`/pick/${item.id}?tipo=live`)} />
        )}
        ListEmptyComponent={
          <Vazio
            icone={<Activity size={32} color={cores.ink4} />}
            titulo={erro ? 'Não foi possível carregar' : 'Nada ao vivo agora'}
            descricao={
              erro ??
              'Quando uma partida em andamento apresentar valor, o pick aparece aqui automaticamente.'
            }
          />
        }
      />
    </View>
  )
}
