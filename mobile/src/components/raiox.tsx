/**
 * Peças do Raio-X no app (07/10/2026) · mesmas leituras do site
 * (website/frontend/src/components/jogos/RaioXDoJogo.tsx), desenhadas em
 * React Native: barra por jogo, seletores segmentados de 44pt+, taxa grande.
 */
import { Pressable, ScrollView, View } from 'react-native'
import { Minus, Plus } from 'lucide-react-native'
import { Txt } from './ui'
import { cores, espaco, raio } from '../theme/tokens'
import { tomDaTaxa, type Lado, type Taxa } from '../lib/raioX'
import { vantagem, type OddDaCasa } from '../lib/oddsDoJogo'

const COR_FORMA: Record<string, { fundo: string; texto: string }> = {
  V: { fundo: cores.green, texto: cores.surface0 },
  E: { fundo: cores.surface3, texto: cores.ink2 },
  D: { fundo: cores.red, texto: cores.surface0 },
}

export function FormaPontos({ forma, pequeno }: { forma: string[]; pequeno?: boolean }) {
  const lado = pequeno ? 14 : 20
  return (
    <View style={{ flexDirection: 'row', gap: 3 }}>
      {[...forma].reverse().map((r, i) => {
        const c = COR_FORMA[r] ?? COR_FORMA.E
        return (
          <View key={i} style={{ width: lado, height: lado, borderRadius: 4, backgroundColor: c.fundo, alignItems: 'center', justifyContent: 'center' }}>
            <Txt variante="rotulo" cor={c.texto} style={{ fontSize: pequeno ? 8 : 10, letterSpacing: 0 }}>{r}</Txt>
          </View>
        )
      })}
    </View>
  )
}

export const COR_TOM = { bom: cores.green, medio: cores.amber, ruim: cores.red, nenhum: cores.ink4 }

export function NumeroDaTaxa({ t, grande }: { t: Taxa; grande?: boolean }) {
  return (
    <View style={{ alignItems: 'flex-end' }}>
      <Txt variante={grande ? 'display' : 'titulo'} cor={COR_TOM[tomDaTaxa(t.pct)]}>{t.n ? `${t.bateu}/${t.n}` : '—'}</Txt>
      <Txt variante="apoio">
        {t.pct != null ? `${Math.round(t.pct * 100)}%` : 'sem dado'}{t.media != null ? ` · média ${t.media.toFixed(1)}` : ''}
      </Txt>
    </View>
  )
}

/** Uma barra por jogo, do mais antigo ao mais recente. Verde = bateu a linha. */
export function Barras({ valores, linha, lado, max }: { valores: Array<number | null>; linha: number; lado: Lado; max?: number }) {
  const serie = [...valores].reverse()
  const teto = max ?? Math.max(linha + 1, ...serie.map((v) => v ?? 0))
  return (
    <View style={{ height: 64, flexDirection: 'row', alignItems: 'flex-end', gap: 3 }}>
      {serie.map((v, i) => {
        const bateu = v != null && v !== linha && (lado === 'mais' ? v > linha : v < linha)
        return (
          <View key={i} style={{ flex: 1, alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
            <Txt variante="apoio" style={{ fontSize: 9 }}>{v == null ? '' : String(v)}</Txt>
            <View style={{
              width: '100%', borderRadius: 3,
              height: `${v == null ? 6 : Math.max(6, (v / teto) * 78)}%`,
              backgroundColor: v == null ? cores.surface2 : bateu ? cores.green : cores.surface3,
            }} />
          </View>
        )
      })}
    </View>
  )
}

export function Chips<T extends string>({ opcoes, valor, onChange }: {
  opcoes: Array<{ id: T; rotulo: string }>; valor: T; onChange: (v: T) => void
}) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0 }}
      contentContainerStyle={{ gap: espaco.sm, paddingHorizontal: espaco.lg }}>
      {opcoes.map((o) => {
        const ativo = o.id === valor
        return (
          <Pressable key={o.id} onPress={() => onChange(o.id)} style={{
            minHeight: 40, paddingHorizontal: espaco.lg, borderRadius: raio.pill, justifyContent: 'center',
            backgroundColor: ativo ? cores.accent : cores.surface2,
          }}>
            <Txt variante="apoio" cor={ativo ? cores.surface0 : cores.ink2} style={{ fontWeight: '700' }}>{o.rotulo}</Txt>
          </Pressable>
        )
      })}
    </ScrollView>
  )
}

/** Seletor de 2 ou 3 opções lado a lado. */
export function Segmento<T extends string>({ opcoes, valor, onChange, desabilitar }: {
  opcoes: Array<{ id: T; rotulo: string }>; valor: T; onChange: (v: T) => void; desabilitar?: (id: T) => boolean
}) {
  return (
    <View style={{ flexDirection: 'row', backgroundColor: cores.surface1, borderRadius: raio.md, padding: 3, borderWidth: 1, borderColor: cores.line }}>
      {opcoes.map((o) => {
        const ativo = o.id === valor
        const off = desabilitar?.(o.id)
        return (
          <Pressable key={o.id} disabled={off} onPress={() => onChange(o.id)} style={{
            flex: 1, minHeight: 42, borderRadius: raio.sm, alignItems: 'center', justifyContent: 'center',
            backgroundColor: ativo ? cores.surface3 : 'transparent', opacity: off ? 0.35 : 1, paddingHorizontal: 4,
          }}>
            <Txt variante="apoio" numberOfLines={1} cor={ativo ? cores.ink1 : cores.ink3} style={{ fontWeight: '700' }}>{o.rotulo}</Txt>
          </Pressable>
        )
      })}
    </View>
  )
}

export function Passo({ rotulo, onMenos, onMais, travaMenos }: {
  rotulo: string; onMenos: () => void; onMais: () => void; travaMenos?: boolean
}) {
  const botao = { width: 48, height: 48, borderRadius: raio.md, borderWidth: 1, borderColor: cores.lineStrong, alignItems: 'center' as const, justifyContent: 'center' as const, backgroundColor: cores.surface1 }
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.md }}>
      <Pressable style={[botao, travaMenos && { opacity: 0.35 }]} disabled={travaMenos} onPress={onMenos} accessibilityLabel="Diminuir linha">
        <Minus size={20} color={cores.ink1} />
      </Pressable>
      <Txt variante="numero" style={{ flex: 1, textAlign: 'center' }}>{rotulo}</Txt>
      <Pressable style={botao} onPress={onMais} accessibilityLabel="Aumentar linha">
        <Plus size={20} color={cores.ink1} />
      </Pressable>
    </View>
  )
}

export function LinhaDaOdd({ odd, bateu, n }: { odd: OddDaCasa | null; bateu: number; n: number }) {
  if (!odd) return null
  const v = vantagem(bateu, n, odd.odd)
  const selo = v == null ? null
    : v >= 0.05 ? { txt: `Valor +${Math.round(v * 100)}%`, cor: cores.green }
    : v > -0.05 ? { txt: 'Odd justa', cor: cores.ink3 }
    : { txt: 'Sem valor', cor: cores.red }
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: espaco.sm, marginTop: espaco.md }}>
      <Txt variante="apoio">Odd</Txt>
      <Txt variante="numero">{odd.odd.toFixed(2)}</Txt>
      {odd.casa ? <Txt variante="apoio">· {odd.casa}</Txt> : null}
      {selo ? (
        <View style={{ marginLeft: 'auto', borderWidth: 1, borderColor: selo.cor, borderRadius: raio.sm, paddingHorizontal: 8, paddingVertical: 3 }}>
          <Txt variante="apoio" cor={selo.cor} style={{ fontWeight: '700' }}>{selo.txt}</Txt>
        </View>
      ) : null}
    </View>
  )
}
