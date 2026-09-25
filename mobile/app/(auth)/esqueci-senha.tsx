/**
 * Recuperação de senha em dois passos, o mesmo fluxo de ForgotPassword.tsx.
 *
 * O backend manda um CÓDIGO de 6 dígitos por e-mail, não um link
 * (`forgot-password` em routers/auth.py), válido por 15 minutos. A versão
 * anterior desta tela parava no primeiro passo e dizia "enviamos um link":
 * quem chegava aqui não tinha onde digitar o código e não conseguia trocar a
 * senha pelo app.
 */
import { useState } from 'react'
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native'
import { useRouter } from 'expo-router'
import { CheckCircle2 } from 'lucide-react-native'
import { autenticacao } from '../../src/api/endpoints'
import { mensagemDeErro } from '../../src/api/client'
import { Botao, Txt, Vazio } from '../../src/components/ui'
import { Campo } from '../../src/components/Campo'
import { cores, espaco } from '../../src/theme/tokens'

/* Mesmo mínimo de `_validate_password` no backend. Checar aqui só poupa uma
   ida ao servidor · quem decide continua sendo ele. */
const SENHA_MINIMA = 10

type Passo = 'email' | 'codigo' | 'pronto'

export default function EsqueciSenha() {
  const router = useRouter()
  const [passo, setPasso] = useState<Passo>('email')
  const [email, setEmail] = useState('')
  const [codigo, setCodigo] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const pedirCodigo = async () => {
    setEnviando(true)
    setErro(null)
    try {
      await autenticacao.esqueciSenha(email.trim())
      setPasso('codigo')
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível enviar o código.'))
    } finally {
      setEnviando(false)
    }
  }

  const redefinir = async () => {
    if (senha.length < SENHA_MINIMA) {
      setErro(`A senha precisa ter pelo menos ${SENHA_MINIMA} caracteres.`)
      return
    }
    setEnviando(true)
    setErro(null)
    try {
      await autenticacao.redefinirSenha(email.trim(), codigo.trim(), senha)
      setPasso('pronto')
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível trocar a senha.'))
    } finally {
      setEnviando(false)
    }
  }

  if (passo === 'pronto') {
    return (
      <View style={{ flex: 1, justifyContent: 'center', padding: espaco.xl, gap: espaco.lg }}>
        <Vazio
          icone={<CheckCircle2 size={40} color={cores.accent} />}
          titulo="Senha alterada"
          descricao="Entre com a senha nova. Por segurança, as sessões abertas em outros aparelhos foram encerradas."
        />
        <Botao titulo="Ir para o login" onPress={() => router.replace('/(auth)/login')} />
      </View>
    )
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ padding: espaco.xl, gap: espaco.lg }} keyboardShouldPersistTaps="handled">
        {passo === 'email' ? (
          <>
            <Txt variante="apoio">
              Informe o e-mail da sua conta. Enviaremos um código de 6 dígitos para você criar uma senha nova.
            </Txt>
            <Campo
              rotulo="E-mail"
              valor={email}
              aoMudar={setEmail}
              teclado="email-address"
              autoComplete="email"
              erro={erro}
            />
            <Botao titulo="Enviar código" onPress={pedirCodigo} carregando={enviando} desabilitado={!email.trim()} />
          </>
        ) : (
          <>
            <Txt variante="apoio">
              Se existir uma conta com {email.trim()}, o código chegou na caixa de entrada. Ele vale por 15 minutos.
            </Txt>
            <Campo
              rotulo="Código"
              valor={codigo}
              aoMudar={(v) => setCodigo(v.replace(/\D/g, ''))}
              placeholder="000000"
              teclado="number-pad"
              autoComplete="off"
              maxLength={6}
            />
            <Campo
              rotulo="Senha nova"
              valor={senha}
              aoMudar={setSenha}
              placeholder={`Pelo menos ${SENHA_MINIMA} caracteres`}
              senha
              autoComplete="new-password"
              erro={erro}
            />
            <Botao
              titulo="Trocar senha"
              onPress={redefinir}
              carregando={enviando}
              desabilitado={codigo.length !== 6 || !senha}
            />
            <Botao
              titulo="Não recebi · enviar de novo"
              variante="fantasma"
              onPress={() => {
                setCodigo('')
                setErro(null)
                setPasso('email')
              }}
            />
          </>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  )
}
