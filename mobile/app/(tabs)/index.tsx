/**
 * Início · o resumo do dia.
 *
 * A home do site é uma página de conversão, com prova social e explicação do
 * produto. No app quem abre já tem conta, então esta tela responde outra
 * pergunta: "o que tem para mim agora?". Destaque do dia, o que está ao vivo
 * e como a banca está indo.
 */
import { useCallback } from 'react'
import { RefreshControl, ScrollView, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Activity, ChevronRight, Crown, Target } from 'lucide-react-native'
import { useAuth } from '../../src/auth/AuthContext'
import { useDados } from '../../src/hooks/useDados'
import { aoVivo, minhasApostas, picks as apiPicks, publico } from '../../src/api/endpoints'
import { Botao, Card, Carregando, Dado, Selo, Txt, Vazio } from '../../src/components/ui'
import { PickCard } from '../../src/components/PickCard'
import { cores, espaco, raio } from '../../src/theme/tokens'
import { reais } from '../../src/lib/formato'

export default function Inicio() {
  const { usuario, isVip } = useAuth()
  const router = useRouter()
  const insets = useSafeAreaInsets()

  const hoje = useDados(() => apiPicks.hoje(), [])
  const resumo = useDados(() => publico.resumoDeHoje(), [])
  const banca = useDados(() => minhasApostas.carregar({ resolved_limit: 1 }), [])
  // O feed ao vivo é VIP no backend · para o free isso responde 403, que o
  // hook trata como erro silencioso e a seção simplesmente não aparece.
  const live = useDados(() => aoVivo.feed(5, false), [], { habilitado: isVip })

  const atualizarTudo = useCallback(() => {
    hoje.atualizar()
    resumo.atualizar()
    banca.atualizar()
    if (isVip) live.atualizar()
  }, [hoje, resumo, banca, live, isVip])

  const destaque = hoje.dados?.vip?.[0] ?? hoje.dados?.dica_do_dia ?? null
  const emAberto = (live.dados?.picks ?? []).filter((p) => !p.result)
  const primeiroNome = usuario?.name?.split(' ')[0] ?? ''

  return (
    <ScrollView
      contentContainerStyle={{ padding: espaco.lg, paddingBottom: insets.bottom + espaco.xxl, gap: espaco.lg }}
      refreshControl={
        <RefreshControl refreshing={hoje.atualizando} onRefresh={atualizarTudo} tintColor={cores.ink3} />
      }
    >
      {/* saudação e plano */}
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: espaco.md }}>
        <View style={{ flex: 1, gap: 2 }}>
          <Txt variante="apoio">Olá{primeiroNome ? `, ${primeiroNome}` : ''}</Txt>
          <Txt variante="titulo">Seu dia no Pick IA</Txt>
        </View>
        {isVip ? (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.xs }}>
            <Crown size={14} color={cores.accent} />
            <Selo texto={usuario?.plan === 'admin' ? 'Admin' : usuario?.plan === 'trial' ? 'Trial' : 'VIP'} cor={cores.accent} />
          </View>
        ) : (
          <Selo texto="Free" cor={cores.ink3} />
        )}
      </View>

      {/* números do dia · vêm do mesmo agregado que a home do site usa */}
      {resumo.dados ? (
        <Card elevado style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          <Dado rotulo="Picks hoje" valor={String(resumo.dados.total ?? 0)} />
          <Dado rotulo="VIP" valor={String(resumo.dados.vip ?? 0)} />
          <Dado rotulo="Múltiplas" valor={String(resumo.dados.multiplas ?? 0)} />
          <Dado rotulo="Alavancagem" valor={String(resumo.dados.alavancagem ?? 0)} />
        </Card>
      ) : null}

      {/* ao vivo · só entra na home quando há algo acontecendo agora */}
      {isVip && emAberto.length > 0 ? (
        <Card
          onPress={() => router.push('/(tabs)/ao-vivo')}
          style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.md }}
        >
          <View style={{ width: 8, height: 8, borderRadius: raio.pill, backgroundColor: cores.red }} />
          <View style={{ flex: 1, gap: 2 }}>
            <Txt variante="corpo" cor={cores.ink1}>
              {emAberto.length === 1 ? '1 oportunidade ao vivo' : `${emAberto.length} oportunidades ao vivo`}
            </Txt>
            <Txt variante="apoio">Partidas em andamento agora</Txt>
          </View>
          <ChevronRight size={18} color={cores.ink3} />
        </Card>
      ) : null}

      {/* destaque do dia */}
      <View style={{ gap: espaco.md }}>
        <Txt variante="rotulo">Destaque de hoje</Txt>
        {hoje.carregando ? (
          <Carregando />
        ) : destaque ? (
          <PickCard pick={destaque} onPress={() => router.push(`/pick/${destaque.id}?tipo=vip`)} />
        ) : (
          <Vazio
            icone={<Target size={32} color={cores.ink4} />}
            titulo="Ainda não há pick publicado"
            descricao="Os picks saem quando o motor encontra valor real. Volte mais tarde."
          />
        )}
      </View>

      {/* banca resumida */}
      {banca.dados && banca.dados.total_resolved > 0 ? (
        <View style={{ gap: espaco.md }}>
          <Txt variante="rotulo">Sua banca</Txt>
          <Card
            onPress={() => router.push('/(tabs)/minhas-apostas')}
            style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}
          >
            <Dado
              rotulo="Resultado"
              valor={reais(banca.dados.total_pnl)}
              cor={banca.dados.total_pnl > 0 ? cores.green : banca.dados.total_pnl < 0 ? cores.red : cores.ink1}
            />
            <Dado rotulo="Acerto" valor={`${banca.dados.win_rate}%`} />
            <Dado rotulo="Apostas" valor={String(banca.dados.total_resolved)} />
            <ChevronRight size={18} color={cores.ink3} />
          </Card>
        </View>
      ) : null}

      {/* convite ao VIP · só para quem não tem */}
      {!isVip ? (
        <Card elevado style={{ gap: espaco.md }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
            <Activity size={18} color={cores.accent} />
            <Txt variante="corpo" cor={cores.ink1}>Picks ao vivo e todos os picks do dia</Txt>
          </View>
          <Txt variante="apoio">
            O plano VIP libera o feed ao vivo, as múltiplas e a alavancagem, além de todos os picks pré-jogo.
          </Txt>
          <Botao titulo="Ver planos" variante="secundario" onPress={() => router.push('/(tabs)/perfil')} />
        </Card>
      ) : null}
    </ScrollView>
  )
}
