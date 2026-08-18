import { useState } from 'react'
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, View } from 'react-native'
import { Check } from 'lucide-react-native'
import { useAuth } from '../../src/auth/AuthContext'
import { mensagemDeErro } from '../../src/api/client'
import { Botao, Txt } from '../../src/components/ui'
import { Campo } from '../../src/components/Campo'
import { cores, espaco, raio } from '../../src/theme/tokens'

/* Máscara só de apresentação · o backend valida e normaliza
   (_validate_phone_br em routers/auth.py). Aqui é para o campo ficar legível
   enquanto se digita, não para validar. */
const soDigitos = (v: string) => v.replace(/\D/g, '')

function mascaraTelefone(v: string) {
  const d = soDigitos(v).slice(0, 11)
  if (d.length <= 10) return d.replace(/(\d{2})(\d)/, '($1) $2').replace(/(\d{4})(\d)/, '$1-$2')
  return d.replace(/(\d{2})(\d)/, '($1) $2').replace(/(\d{5})(\d)/, '$1-$2')
}

export default function Cadastro() {
  const { cadastrar } = useAuth()

  const [nome, setNome] = useState('')
  const [usuario, setUsuario] = useState('')
  const [email, setEmail] = useState('')
  const [telefone, setTelefone] = useState('')
  const [senha, setSenha] = useState('')
  const [aceitou, setAceitou] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const submeter = async () => {
    if (!aceitou) {
      setErro('É preciso aceitar os termos de uso para criar a conta.')
      return
    }
    setEnviando(true)
    setErro(null)
    try {
      await cadastrar({
        name: nome.trim(),
        email: email.trim(),
        password: senha,
        phone: soDigitos(telefone),
        username: usuario.trim().toLowerCase(),
        accepted_terms: true,
      })
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível criar a conta.'))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={{ padding: espaco.xl, gap: espaco.lg, paddingBottom: espaco.xxl * 2 }}
        keyboardShouldPersistTaps="handled"
      >
        <Campo rotulo="Nome completo" valor={nome} aoMudar={setNome} autoCapitalize="words" autoComplete="name" />
        <Campo
          rotulo="Nome de usuário"
          valor={usuario}
          aoMudar={setUsuario}
          placeholder="3 a 20 caracteres, sem espaço"
          autoComplete="username"
          maxLength={20}
        />
        <Campo rotulo="E-mail" valor={email} aoMudar={setEmail} teclado="email-address" autoComplete="email" />
        <Campo
          rotulo="Telefone"
          valor={telefone}
          aoMudar={(v) => setTelefone(mascaraTelefone(v))}
          placeholder="(11) 90000-0000"
          teclado="phone-pad"
          autoComplete="tel"
        />
        <Campo
          rotulo="Senha"
          valor={senha}
          aoMudar={setSenha}
          placeholder="Mínimo de 8 caracteres"
          senha
          autoComplete="new-password"
          erro={erro}
        />

        <Pressable
          onPress={() => setAceitou((a) => !a)}
          style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.md, paddingVertical: espaco.sm }}
          hitSlop={8}
        >
          <View
            style={{
              width: 22,
              height: 22,
              borderRadius: raio.sm,
              borderWidth: 2,
              borderColor: aceitou ? cores.accent : cores.lineStrong,
              backgroundColor: aceitou ? cores.accent : 'transparent',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {aceitou ? <Check size={14} color={cores.surface0} strokeWidth={3} /> : null}
          </View>
          <Txt variante="apoio" style={{ flex: 1 }}>
            Li e aceito os termos de uso e a política de privacidade.
          </Txt>
        </Pressable>

        <Botao titulo="Criar conta" onPress={submeter} carregando={enviando} desabilitado={!aceitou} />
      </ScrollView>
    </KeyboardAvoidingView>
  )
}
