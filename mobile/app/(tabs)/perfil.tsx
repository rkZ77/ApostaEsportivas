/**
 * Perfil · conta, plano e sessão.
 *
 * Assinatura NÃO é vendida aqui de propósito. Cobrança dentro do app entra
 * nas regras de billing das lojas e mexe no fluxo de pagamento existente
 * (MercadoPago). O app mostra o estado do plano; a oferta de plano só aparece
 * se `OFERECE_PLANO_NO_APP` for ligado (ver src/config/env.ts).
 *
 * Termos, Privacidade e a exclusão de conta ficam aqui porque as lojas exigem
 * os três acessíveis de dentro do app.
 */
import { useState, type ReactNode } from 'react'
import { Alert, Linking, Pressable, ScrollView, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useRouter } from 'expo-router'
import { ChevronRight, Crown, ExternalLink, FileText, ServerCog, ShieldCheck } from 'lucide-react-native'
import { useAuth } from '../../src/auth/AuthContext'
import { rotuloDoPlano } from '../../src/auth/plano'
import { Botao, Card, Dado, Selo, Separador, Txt } from '../../src/components/ui'
import { cores, espaco } from '../../src/theme/tokens'
import { AMBIENTE, API_BASE_URL, OFERECE_PLANO_NO_APP, SITE_URL as SITE } from '../../src/config/env'

export default function Perfil() {
  const { usuario, isVip, isPro, sair } = useAuth()
  const insets = useSafeAreaInsets()
  const router = useRouter()
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

  const rotuloPlano = rotuloDoPlano(usuario)

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

      {/* Só com OFERECE_PLANO_NO_APP (ver src/config/env.ts). `!isPro` e não `!isVip`: quem assina o Pick IA também tem pra onde
          subir, e sem isto o app não oferecia o upgrade em lugar nenhum. */}
      {OFERECE_PLANO_NO_APP && !isPro ? (
        <Card elevado style={{ gap: espaco.md }}>
          <Txt variante="corpo" cor={cores.ink1}>
            {isVip ? 'Fazer upgrade para o Pick IA Pro' : 'Ver os planos'}
          </Txt>
          <Txt variante="apoio">
            {isVip
              ? 'O Pick IA Pro acrescenta os picks ao vivo e o agente de futebol. A troca é feita no site, com o mesmo login desta conta.'
              : 'A assinatura é feita no site, com o mesmo login desta conta. Ao voltar ao app, seu plano já estará ativo.'}
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

      <Card style={{ gap: espaco.xs }}>
        <Txt variante="rotulo">Documentos</Txt>
        <LinhaDeLink icone={<FileText size={16} color={cores.ink3} />} titulo="Termos de Uso"
          onPress={() => Linking.openURL(`${SITE}/termos`)} />
        <LinhaDeLink icone={<ShieldCheck size={16} color={cores.ink3} />} titulo="Política de Privacidade"
          onPress={() => Linking.openURL(`${SITE}/privacidade`)} />
      </Card>

      {/* Mesmo aviso do rodapé do site. O Pick IA publica análises e palpites
          gerados pelo sistema; não aceita apostas nem guarda dinheiro. */}
      <Txt variante="apoio" cor={cores.ink4} style={{ textAlign: 'center' }}>
        Conteúdo para maiores de 18 anos. Os picks são análises geradas por IA, não garantia de resultado.
        Aposte com responsabilidade.
      </Txt>

      <Botao titulo="Excluir minha conta" variante="fantasma" onPress={() => router.push('/conta/excluir')} />

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

function LinhaDeLink({ icone, titulo, onPress }: { icone: ReactNode; titulo: string; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.md, minHeight: 44 }}
      accessibilityRole="link"
    >
      {icone}
      <Txt variante="corpo" cor={cores.ink1} style={{ flex: 1 }}>{titulo}</Txt>
      <ChevronRight size={16} color={cores.ink4} />
    </Pressable>
  )
}
