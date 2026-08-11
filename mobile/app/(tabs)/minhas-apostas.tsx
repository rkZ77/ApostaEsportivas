/**
 * Minhas Apostas · consome `GET /api/banca`, a mesma rota da página Banca.
 *
 * Todos os números (P&L, ROI, taxa de acerto, sequência) chegam calculados
 * do backend. O app não soma nada: se somasse, existiriam duas contas do
 * mesmo saldo e uma hora elas divergiriam.
 */
import { useMemo, useState } from 'react'
import { FlatList, Image, Pressable, RefreshControl, ScrollView, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { ListChecks } from 'lucide-react-native'
import { useDados } from '../../src/hooks/useDados'
import { minhasApostas } from '../../src/api/endpoints'
import { Card, Carregando, Dado, Selo, Separador, Txt, Vazio } from '../../src/components/ui'
import { cores, espaco, raio } from '../../src/theme/tokens'
import { escudo, estiloDoResultado, mercadoCompleto, odd, reais, unidades } from '../../src/lib/formato'
import type { Aposta } from '../../src/api/types'

type Aba = 'abertas' | 'ganhas' | 'perdidas' | 'todas'

const ABAS: { chave: Aba; rotulo: string }[] = [
  { chave: 'abertas', rotulo: 'Em andamento' },
  { chave: 'ganhas', rotulo: 'Ganhas' },
  { chave: 'perdidas', rotulo: 'Perdidas' },
  { chave: 'todas', rotulo: 'Todas' },
]

function LinhaAposta({ aposta }: { aposta: Aposta }) {
  const estilo = estiloDoResultado(aposta.result)
  const uriCasa = escudo(aposta.home_team_id)
  const uriFora = escudo(aposta.away_team_id)

  return (
    <Card style={{ gap: espaco.md }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
        {uriCasa ? <Image source={{ uri: uriCasa }} style={{ width: 18, height: 18 }} resizeMode="contain" /> : null}
        {uriFora ? <Image source={{ uri: uriFora }} style={{ width: 18, height: 18 }} resizeMode="contain" /> : null}
        <Txt variante="corpo" numberOfLines={1} style={{ flex: 1, color: cores.ink1 }}>
          {aposta.home_team_name ?? '—'} · {aposta.away_team_name ?? '—'}
        </Txt>
        <Selo texto={estilo.rotulo} cor={estilo.cor} preenchido={Boolean(aposta.result)} />
      </View>

      <Txt variante="apoio" numberOfLines={2}>
        {mercadoCompleto(aposta.market, aposta.line)}
      </Txt>

      <Separador />

      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Dado rotulo="Stake" valor={unidades(aposta.stake_units)} />
        <Dado rotulo="Odd" valor={odd(aposta.actual_odd ?? aposta.odd)} />
        <Dado
          rotulo="Resultado"
          valor={aposta.pnl == null ? '—' : reais(aposta.pnl)}
          cor={aposta.pnl == null ? cores.ink3 : aposta.pnl > 0 ? cores.green : aposta.pnl < 0 ? cores.red : cores.ink1}
        />
      </View>
    </Card>
  )
}

export default function MinhasApostas() {
  const insets = useSafeAreaInsets()
  const [aba, setAba] = useState<Aba>('abertas')

  const { dados, carregando, atualizando, erro, atualizar } = useDados(
    () => minhasApostas.carregar({ resolved_limit: 200 }),
    [],
  )

  const lista = useMemo(() => {
    const entradas = dados?.entries ?? []
    if (aba === 'abertas') return entradas.filter((e) => !e.result)
    if (aba === 'ganhas') return entradas.filter((e) => e.result === 'GREEN' || e.result === 'HALF-WIN')
    if (aba === 'perdidas') return entradas.filter((e) => e.result === 'RED' || e.result === 'HALF-LOSS')
    return entradas
  }, [dados, aba])

  if (carregando) return <Carregando texto="Carregando suas apostas" />

  return (
    <FlatList
      data={lista}
      keyExtractor={(item) => `${item.pick_type}-${item.id}`}
      contentContainerStyle={{
        paddingHorizontal: espaco.lg,
        paddingBottom: insets.bottom + espaco.xxl,
        gap: espaco.md,
        flexGrow: 1,
      }}
      refreshControl={<RefreshControl refreshing={atualizando} onRefresh={atualizar} tintColor={cores.ink3} />}
      ListHeaderComponent={
        <View style={{ gap: espaco.lg, paddingTop: espaco.md, paddingBottom: espaco.sm }}>
          {/* estatísticas · exatamente como o backend devolve */}
          {dados ? (
            <Card elevado style={{ gap: espaco.lg }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <Dado
                  rotulo="Resultado"
                  valor={reais(dados.total_pnl)}
                  cor={dados.total_pnl > 0 ? cores.green : dados.total_pnl < 0 ? cores.red : cores.ink1}
                />
                <Dado rotulo="Acerto" valor={`${dados.win_rate}%`} />
                <Dado rotulo="Yield" valor={`${dados.yield_roi}%`} />
              </View>
              <Separador />
              <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <Dado rotulo="Green" valor={String(dados.greens)} cor={cores.green} />
                <Dado rotulo="Red" valor={String(dados.reds)} cor={cores.red} />
                <Dado rotulo="Anuladas" valor={String(dados.push)} />
                <Dado rotulo="Banca" valor={reais(dados.bankroll_current)} />
              </View>
            </Card>
          ) : null}

          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: espaco.sm }}
            style={{ flexGrow: 0 }}
          >
            {ABAS.map(({ chave, rotulo }) => {
              const ativo = aba === chave
              return (
                <Pressable
                  key={chave}
                  onPress={() => setAba(chave)}
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
        </View>
      }
      renderItem={({ item }) => <LinhaAposta aposta={item} />}
      ListEmptyComponent={
        <Vazio
          icone={<ListChecks size={32} color={cores.ink4} />}
          titulo={erro ? 'Não foi possível carregar' : 'Nenhuma aposta aqui'}
          descricao={
            erro ??
            'Ao seguir um pick, ele passa a contar na sua banca e aparece nesta lista.'
          }
        />
      }
    />
  )
}
