import { useState } from 'react'
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, View } from 'react-native'
import { Link } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { ShieldAlert } from 'lucide-react-native'
import { useAuth } from '../../src/auth/AuthContext'
import { mensagemDeErro } from '../../src/api/client'
import { Botao, Card, Txt } from '../../src/components/ui'
import { Campo } from '../../src/components/Campo'
import { cores, espaco, fonte, peso } from '../../src/theme/tokens'
import { AMBIENTE, API_BASE_URL } from '../../src/config/env'

export default function Login() {
  const { entrar, sessaoDerrubadaEm } = useAuth()
  const insets = useSafeAreaInsets()

  const [identificador, setIdentificador] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const submeter = async () => {
    if (!identificador.trim() || !senha) {
      setErro('Preencha e-mail e senha.')
      return
    }
    setEnviando(true)
    setErro(null)
    try {
      await entrar(identificador.trim(), senha)
      // A guarda de rota no _layout leva para as abas assim que o usuário muda.
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível entrar. Confira seus dados.'))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={{
          flexGrow: 1,
          justifyContent: 'center',
          padding: espaco.xl,
          paddingTop: insets.top + espaco.xl,
          gap: espaco.xl,
        }}
        keyboardShouldPersistTaps="handled"
      >
        <View style={{ gap: espaco.sm }}>
          <Txt variante="display">
            Pick <Txt variante="display" cor={cores.accent}>IA</Txt>
          </Txt>
          <Txt variante="apoio">Entre para ver os picks do dia.</Txt>
        </View>

        {sessaoDerrubadaEm ? (
          <Card elevado style={{ flexDirection: 'row', gap: espaco.md, alignItems: 'flex-start' }}>
            <ShieldAlert size={20} color={cores.amber} />
            <View style={{ flex: 1, gap: espaco.xs }}>
              <Txt variante="corpo" cor={cores.ink1}>Sua sessão foi encerrada</Txt>
              <Txt variante="apoio">
                Detectamos um login em {sessaoDerrubadaEm}. Sua conta permite um dispositivo por vez.
              </Txt>
            </View>
          </Card>
        ) : null}

        <View style={{ gap: espaco.lg }}>
          <Campo
            rotulo="E-mail ou usuário"
            valor={identificador}
            aoMudar={setIdentificador}
            placeholder="voce@email.com"
            teclado="email-address"
            autoComplete="email"
          />
          <Campo
            rotulo="Senha"
            valor={senha}
            aoMudar={setSenha}
            placeholder="Sua senha"
            senha
            autoComplete="password"
            erro={erro}
          />

          <Botao titulo="Entrar" onPress={submeter} carregando={enviando} />

          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <Link href="/(auth)/esqueci-senha" asChild>
              <Pressable hitSlop={8}>
                <Txt variante="apoio" cor={cores.ink2}>Esqueci minha senha</Txt>
              </Pressable>
            </Link>
            <Link href="/(auth)/cadastro" asChild>
              <Pressable hitSlop={8}>
                <Txt variante="apoio" cor={cores.accent} style={{ fontWeight: peso.semi }}>
                  Criar conta
                </Txt>
              </Pressable>
            </Link>
          </View>
        </View>

        {/* Faixa de ambiente · deixa explícito de onde o app está lendo,
            para nunca haver dúvida se um teste tocou produção. */}
        {AMBIENTE === 'dev' ? (
          <View style={{ alignItems: 'center', gap: 2 }}>
            <Txt variante="rotulo" cor={cores.amber}>Ambiente de desenvolvimento</Txt>
            <Txt style={{ fontSize: fonte.xs, color: cores.ink4 }}>{API_BASE_URL}</Txt>
          </View>
        ) : null}
      </ScrollView>
    </KeyboardAvoidingView>
  )
}
