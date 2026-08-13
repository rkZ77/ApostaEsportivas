/**
 * Primitivos visuais do app.
 *
 * Equivalente nativo de `website/frontend/src/components/ui` -- mesma
 * linguagem (card escuro, borda fina, verde só onde é sinal), adaptada ao
 * toque: alvos maiores, menos densidade, sem hover.
 */
import type { ReactNode } from 'react'
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native'
import { cores, espaco, fonte, peso, raio } from '../theme/tokens'

/* ── texto ────────────────────────────────────────────────────────────── */

type VarianteTexto = 'titulo' | 'display' | 'corpo' | 'apoio' | 'rotulo' | 'numero'

const ESTILO_TEXTO: Record<VarianteTexto, TextStyle> = {
  display: { fontSize: fonte.display, fontWeight: peso.bold, color: cores.ink1 },
  titulo: { fontSize: fonte.xl, fontWeight: peso.semi, color: cores.ink1 },
  numero: { fontSize: fonte.lg, fontWeight: peso.semi, color: cores.ink1, fontVariant: ['tabular-nums'] },
  corpo: { fontSize: fonte.base, fontWeight: peso.normal, color: cores.ink2 },
  apoio: { fontSize: fonte.sm, fontWeight: peso.normal, color: cores.ink3 },
  rotulo: { fontSize: fonte.xs, fontWeight: peso.semi, color: cores.ink3, letterSpacing: 0.6, textTransform: 'uppercase' },
}

export function Txt({
  variante = 'corpo',
  cor,
  style,
  children,
  numberOfLines,
}: {
  variante?: VarianteTexto
  cor?: string
  style?: StyleProp<TextStyle>
  children: ReactNode
  numberOfLines?: number
}) {
  return (
    <Text numberOfLines={numberOfLines} style={[ESTILO_TEXTO[variante], cor ? { color: cor } : null, style]}>
      {children}
    </Text>
  )
}

/* ── card ─────────────────────────────────────────────────────────────── */

export function Card({
  children,
  style,
  onPress,
  elevado,
}: {
  children: ReactNode
  style?: StyleProp<ViewStyle>
  onPress?: () => void
  elevado?: boolean
}) {
  const base: ViewStyle = {
    backgroundColor: elevado ? cores.surface2 : cores.surface1,
    borderColor: cores.line,
    borderWidth: StyleSheet.hairlineWidth * 2,
    borderRadius: raio.lg,
    padding: espaco.lg,
  }
  if (!onPress) return <View style={[base, style]}>{children}</View>
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [base, pressed && { backgroundColor: cores.surface3 }, style]}
    >
      {children}
    </Pressable>
  )
}

/* ── selo ─────────────────────────────────────────────────────────────── */

export function Selo({ texto, cor = cores.ink3, preenchido }: { texto: string; cor?: string; preenchido?: boolean }) {
  return (
    <View
      style={{
        alignSelf: 'flex-start',
        paddingHorizontal: espaco.sm,
        paddingVertical: 3,
        borderRadius: raio.pill,
        backgroundColor: preenchido ? cor : 'transparent',
        borderWidth: preenchido ? 0 : StyleSheet.hairlineWidth * 2,
        borderColor: cor,
      }}
    >
      <Text
        style={{
          fontSize: fonte.xs,
          fontWeight: peso.semi,
          color: preenchido ? cores.surface0 : cor,
          letterSpacing: 0.3,
        }}
      >
        {texto}
      </Text>
    </View>
  )
}

/* ── botão ────────────────────────────────────────────────────────────── */

export function Botao({
  titulo,
  onPress,
  variante = 'primario',
  carregando,
  desabilitado,
  style,
}: {
  titulo: string
  onPress: () => void
  variante?: 'primario' | 'secundario' | 'fantasma'
  carregando?: boolean
  desabilitado?: boolean
  style?: StyleProp<ViewStyle>
}) {
  const inativo = desabilitado || carregando
  const fundo =
    variante === 'primario' ? cores.accent : variante === 'secundario' ? cores.surface2 : 'transparent'
  const corTexto = variante === 'primario' ? cores.surface0 : cores.ink1

  return (
    <Pressable
      onPress={onPress}
      disabled={inativo}
      style={({ pressed }) => [
        {
          minHeight: 48, // alvo de toque confortável
          borderRadius: raio.md,
          alignItems: 'center',
          justifyContent: 'center',
          paddingHorizontal: espaco.lg,
          backgroundColor: pressed && variante === 'primario' ? cores.accentPress : fundo,
          borderWidth: variante === 'fantasma' ? StyleSheet.hairlineWidth * 2 : 0,
          borderColor: cores.lineStrong,
          opacity: inativo ? 0.5 : 1,
        },
        style,
      ]}
    >
      {carregando ? (
        <ActivityIndicator color={corTexto} />
      ) : (
        <Text style={{ fontSize: fonte.base, fontWeight: peso.semi, color: corTexto }}>{titulo}</Text>
      )}
    </Pressable>
  )
}

/* ── estados de tela ──────────────────────────────────────────────────── */

export function Carregando({ texto }: { texto?: string }) {
  return (
    <View style={{ paddingVertical: espaco.xxl, alignItems: 'center', gap: espaco.md }}>
      <ActivityIndicator color={cores.accent} />
      {texto ? <Txt variante="apoio">{texto}</Txt> : null}
    </View>
  )
}

export function Vazio({
  titulo,
  descricao,
  icone,
  acao,
}: {
  titulo: string
  descricao?: string
  icone?: ReactNode
  acao?: ReactNode
}) {
  return (
    <View style={{ paddingVertical: espaco.xxl, paddingHorizontal: espaco.lg, alignItems: 'center', gap: espaco.md }}>
      {icone}
      <Txt variante="titulo" style={{ textAlign: 'center' }}>
        {titulo}
      </Txt>
      {descricao ? (
        <Txt variante="apoio" style={{ textAlign: 'center', maxWidth: 320 }}>
          {descricao}
        </Txt>
      ) : null}
      {acao}
    </View>
  )
}

/** Linha rótulo/valor · a unidade de informação mais repetida do app. */
export function Dado({ rotulo, valor, cor }: { rotulo: string; valor: string; cor?: string }) {
  return (
    <View style={{ gap: 2 }}>
      <Txt variante="rotulo">{rotulo}</Txt>
      <Txt variante="numero" cor={cor}>
        {valor}
      </Txt>
    </View>
  )
}

export function Separador() {
  return <View style={{ height: StyleSheet.hairlineWidth * 2, backgroundColor: cores.line }} />
}
