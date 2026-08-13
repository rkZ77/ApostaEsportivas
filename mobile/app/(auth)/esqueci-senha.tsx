import { useState } from 'react'
import { ScrollView, View } from 'react-native'
import { MailCheck } from 'lucide-react-native'
import { autenticacao } from '../../src/api/endpoints'
import { mensagemDeErro } from '../../src/api/client'
import { Botao, Txt, Vazio } from '../../src/components/ui'
import { Campo } from '../../src/components/Campo'
import { cores, espaco } from '../../src/theme/tokens'

export default function EsqueciSenha() {
  const [email, setEmail] = useState('')
  const [enviado, setEnviado] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const submeter = async () => {
    setEnviando(true)
    setErro(null)
    try {
      await autenticacao.esqueciSenha(email.trim())
      setEnviado(true)
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível enviar o e-mail.'))
    } finally {
      setEnviando(false)
    }
  }

  if (enviado) {
    return (
      <View style={{ flex: 1, justifyContent: 'center' }}>
        <Vazio
          icone={<MailCheck size={40} color={cores.accent} />}
          titulo="E-mail enviado"
          descricao="Se existir uma conta com esse e-mail, o link para redefinir a senha chegou na caixa de entrada. O link é válido por tempo limitado."
        />
      </View>
    )
  }

  return (
    <ScrollView contentContainerStyle={{ padding: espaco.xl, gap: espaco.lg }} keyboardShouldPersistTaps="handled">
      <Txt variante="apoio">
        Informe o e-mail da sua conta. Enviaremos um link para você criar uma senha nova.
      </Txt>
      <Campo
        rotulo="E-mail"
        valor={email}
        aoMudar={setEmail}
        teclado="email-address"
        autoComplete="email"
        erro={erro}
      />
      <Botao titulo="Enviar link" onPress={submeter} carregando={enviando} desabilitado={!email.trim()} />
    </ScrollView>
  )
}
