/**
 * Campo de formulário. Um só componente para todo o app, porque teclado no
 * celular é o ponto de maior atrito: tipo de teclado, autocomplete e
 * capitalização precisam estar certos em cada campo, e centralizar isso
 * evita ter que lembrar disso em cada tela.
 */
import { useState } from 'react'
import { Pressable, StyleSheet, TextInput, View, type KeyboardTypeOptions } from 'react-native'
import { Eye, EyeOff } from 'lucide-react-native'
import { Txt } from './ui'
import { cores, espaco, fonte, raio } from '../theme/tokens'

export function Campo({
  rotulo,
  valor,
  aoMudar,
  placeholder,
  senha,
  teclado,
  autoComplete,
  autoCapitalize = 'none',
  erro,
  maxLength,
}: {
  rotulo: string
  valor: string
  aoMudar: (v: string) => void
  placeholder?: string
  senha?: boolean
  teclado?: KeyboardTypeOptions
  autoComplete?: 'email' | 'username' | 'password' | 'new-password' | 'tel' | 'name' | 'off'
  autoCapitalize?: 'none' | 'words' | 'sentences'
  erro?: string | null
  maxLength?: number
}) {
  const [visivel, setVisivel] = useState(false)
  const [focado, setFocado] = useState(false)

  return (
    <View style={{ gap: espaco.sm }}>
      <Txt variante="rotulo">{rotulo}</Txt>
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          backgroundColor: cores.surface2,
          borderRadius: raio.md,
          borderWidth: StyleSheet.hairlineWidth * 2,
          borderColor: erro ? cores.red : focado ? cores.lineStrong : cores.line,
          paddingHorizontal: espaco.md,
        }}
      >
        <TextInput
          value={valor}
          onChangeText={aoMudar}
          placeholder={placeholder}
          placeholderTextColor={cores.ink4}
          secureTextEntry={senha && !visivel}
          keyboardType={teclado}
          autoComplete={autoComplete}
          autoCapitalize={autoCapitalize}
          autoCorrect={false}
          maxLength={maxLength}
          onFocus={() => setFocado(true)}
          onBlur={() => setFocado(false)}
          style={{
            flex: 1,
            minHeight: 48,
            color: cores.ink1,
            fontSize: fonte.base,
          }}
        />
        {senha ? (
          <Pressable onPress={() => setVisivel((v) => !v)} hitSlop={12} style={{ padding: espaco.xs }}>
            {visivel ? <EyeOff size={18} color={cores.ink3} /> : <Eye size={18} color={cores.ink3} />}
          </Pressable>
        ) : null}
      </View>
      {erro ? <Txt variante="apoio" cor={cores.red}>{erro}</Txt> : null}
    </View>
  )
}
