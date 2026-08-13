/**
 * Perfil · conta, plano e sessão.
 *
 * Assinatura NÃO é vendida aqui de propósito. Cobrança dentro do app entra
 * nas regras de billing das lojas e mexe no fluxo de pagamento existente
 * (MercadoPago), que está fora do escopo desta fase. Por enquanto o app
 * mostra o estado do plano e manda para o site quando for o caso.
 */
import { useState } from 'react'
import { Alert, Linking, ScrollView, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Crown, ExternalLink, ServerCog } from 'lucide-react-native'
import { useAuth } from '../../src/auth/AuthContext'
import { Botao, Card, Dado, Selo, Separador, Txt } from '../../src/components/ui'
import { cores, espaco } from '../../src/theme/tokens'
import { AMBIENTE, API_BASE_URL } from '../../src/config/env'

const SITE = 'https://pickia.com.br'

export default function Perfil() {
  const { usuario, isVip, sair } = useAuth()
  const insets = useSafeAreaInsets()
  const [saindo, setSaindo] = useState(false)

  const confirmarSaida = () => {
    Alert.alert('Sair da conta', 'Você precisará entrar novamente para ver os picks.', [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Sair',
        style: 'destructive',
        onPress: async () => {
          setSaindo(true)
          await sair()
          setSaindo(false)
        },
      },
    ])
  }

  const rotuloPlano =
    usuario?.plan === 'admin' ? 'Admin' : usuario?.plan === 'trial' ? 'Trial' : usuario?.plan === 'vip' ? 'VIP' : 'Free'

  const expira = usuario?.expires_at ? usuario.expires_at.slice(0, 10).split('-').reverse().join('/') : null

  return (
    <ScrollView
      contentContainerStyle={{ padding: espaco.lg, paddingBottom: insets.bottom + espaco.xxl, gap: espaco.lg }}
    >
      <Card style={{ gap: espaco.md }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: espaco.md }}>
          <View style={{ flex: 1, gap: 2 }}>
            <Txt variante="titulo" numberOfLines={1}>{usuario?.name ?? '—'}</Txt>
            <Txt variante="apoio" numberOfLines={1}>{usuario?.email ?? ''}</Txt>
          </View>
          {isVip ? <Crown size={20} color={cores.accent} /> : null}
        </View>

        <Separador />

        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <View style={{ gap: espaco.xs }}>
            <Txt variante="rotulo">Plano</Txt>
            <Selo texto={rotuloPlano} cor={isVip ? cores.accent : cores.ink3} preenchido={isVip} />
          </View>
          {expira ? <Dado rotulo={isVip ? 'Válido até' : 'Expirou em'} valor={expira} /> : null}
        </View>
      </Card>

      {!isVip ? (
        <Card elevado style={{ gap: espaco.md }}>
          <Txt variante="corpo" cor={cores.ink1}>Assinar o VIP</Txt>
          <Txt variante="apoio">
            A assinatura é feita no site, com o mesmo login desta conta. Ao voltar ao app, seu plano já estará ativo.
          </Txt>
          <Botao
            titulo="Abrir planos no site"
            variante="secundario"
            onPress={() => Linking.openURL(`${SITE}/planos`)}
          />
        </Card>
      ) : null}

      <Card style={{ gap: espaco.md }}>
        <Txt variante="rotulo">Conta</Txt>
        <Botao
          titulo="Gerenciar no site"
          variante="fantasma"
          onPress={() => Linking.openURL(`${SITE}/perfil`)}
        />
        <Botao titulo="Sair da conta" variante="fantasma" onPress={confirmarSaida} carregando={saindo} />
      </Card>

      {/* Ambiente à vista · a forma mais barata de nunca confundir DEV com produção. */}
      <Card style={{ gap: espaco.sm }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm }}>
          <ServerCog size={16} color={AMBIENTE === 'dev' ? cores.amber : cores.ink3} />
          <Txt variante="rotulo" cor={AMBIENTE === 'dev' ? cores.amber : cores.ink3}>
            {AMBIENTE === 'dev' ? 'Ambiente de desenvolvimento' : 'Produção'}
          </Txt>
        </View>
        <Txt variante="apoio" numberOfLines={1}>{API_BASE_URL}</Txt>
      </Card>

      <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.xs, justifyContent: 'center' }}>
        <ExternalLink size={12} color={cores.ink4} />
        <Txt variante="apoio" cor={cores.ink4}>pickia.com.br</Txt>
      </View>
    </ScrollView>
  )
}
