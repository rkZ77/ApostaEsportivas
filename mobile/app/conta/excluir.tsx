/**
 * Excluir a conta dentro do app.
 *
 * Exigência das duas lojas: a Apple (diretriz 5.1.1(v)) pede que o app que
 * cria conta também permita excluí-la sem sair dele. A regra da exclusão é
 * toda do backend (`delete-account` em routers/auth.py): anonimiza a conta,
 * apaga o que a pessoa produziu e mantém a trilha fiscal dos pagamentos. Esta
 * tela só coleta as mesmas duas confirmações que o Perfil do site coleta.
 */
import { useState } from 'react'
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native'
import { TriangleAlert } from 'lucide-react-native'
import { useAuth } from '../../src/auth/AuthContext'
import { autenticacao } from '../../src/api/endpoints'
import { mensagemDeErro } from '../../src/api/client'
import { limparSessao } from '../../src/api/session'
import { Botao, Card, Txt } from '../../src/components/ui'
import { Campo } from '../../src/components/Campo'
import { cores, espaco } from '../../src/theme/tokens'

const PALAVRA = 'EXCLUIR'

export default function ExcluirConta() {
  const { usuario, sair } = useAuth()
  // Ausente vale "tem senha": pedir a senha a mais só custa um erro 400 claro;
  // não pedir quando precisa trava a tela sem explicação.
  const pedeSenha = usuario?.tem_senha !== false

  const [senha, setSenha] = useState('')
  const [confirmacao, setConfirmacao] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const pronto = confirmacao.trim().toUpperCase() === PALAVRA && (!pedeSenha || senha.length > 0)

  const excluir = async () => {
    setEnviando(true)
    setErro(null)
    try {
      await autenticacao.excluirConta(pedeSenha ? senha : null, confirmacao.trim())
      // A conta já não existe: o logout do servidor responderia 401. Limpa o
      // aparelho e deixa `sair` zerar o estado · a guarda leva para o login.
      await limparSessao()
      await sair()
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível excluir a conta.'))
      setEnviando(false)
    }
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ padding: espaco.lg, gap: espaco.lg }} keyboardShouldPersistTaps="handled">
        <Card elevado style={{ flexDirection: 'row', gap: espaco.md, alignItems: 'flex-start' }}>
          <TriangleAlert size={20} color={cores.red} />
          <View style={{ flex: 1, gap: espaco.xs }}>
            <Txt variante="corpo" cor={cores.ink1}>Esta ação não pode ser desfeita</Txt>
            <Txt variante="apoio">
              A conta é excluída no app e no site. Seus registros de pagamento são mantidos por obrigação fiscal, já
              sem vínculo com seus dados pessoais. Se você tem assinatura ativa, ela será perdida sem reembolso.
            </Txt>
          </View>
        </Card>

        {pedeSenha ? (
          <Campo rotulo="Senha atual" valor={senha} aoMudar={setSenha} senha autoComplete="password" />
        ) : null}

        <Campo
          rotulo={`Digite ${PALAVRA} para confirmar`}
          valor={confirmacao}
          aoMudar={setConfirmacao}
          autoCapitalize="none"
          autoComplete="off"
          erro={erro}
        />

        <Botao titulo="Excluir minha conta" onPress={excluir} carregando={enviando} desabilitado={!pronto} />
      </ScrollView>
    </KeyboardAvoidingView>
  )
}
