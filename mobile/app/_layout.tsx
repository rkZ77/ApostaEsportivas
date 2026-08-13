/**
 * Raiz do app: tema escuro, provider de sessão e a guarda de rota.
 */
import { useEffect } from 'react'
import { ActivityIndicator, View } from 'react-native'
import { Stack, useRouter, useSegments } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { AuthProvider, useAuth } from '../src/auth/AuthContext'
import { cores } from '../src/theme/tokens'

/**
 * Guarda de navegação.
 *
 * Uma única regra, em um lugar só: sem sessão, o app fica no grupo (auth);
 * com sessão, fica no grupo (tabs). Isso cobre de uma vez o primeiro acesso,
 * o logout e a sessão derrubada por login em outro aparelho -- em todos os
 * casos o `usuario` vira null e a navegação reage sozinha.
 */
function Guarda() {
  const { usuario, carregando } = useAuth()
  const segmentos = useSegments()
  const router = useRouter()

  useEffect(() => {
    if (carregando) return
    const emTelaDeAuth = segmentos[0] === '(auth)'

    if (!usuario && !emTelaDeAuth) {
      router.replace('/(auth)/login')
    } else if (usuario && emTelaDeAuth) {
      router.replace('/(tabs)')
    }
  }, [usuario, carregando, segmentos, router])

  if (carregando) {
    return (
      <View style={{ flex: 1, backgroundColor: cores.surface0, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={cores.accent} size="large" />
      </View>
    )
  }

  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: cores.surface0 },
        headerTintColor: cores.ink1,
        headerTitleStyle: { fontWeight: '600' },
        headerShadowVisible: false,
        contentStyle: { backgroundColor: cores.surface0 },
      }}
    >
      <Stack.Screen name="(auth)" options={{ headerShown: false }} />
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="pick/[id]" options={{ title: 'Pick' }} />
    </Stack>
  )
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        {/* No SDK 57 o Android é edge-to-edge · a cor da barra vem do fundo da tela. */}
        <StatusBar style="light" />
        <Guarda />
      </AuthProvider>
    </SafeAreaProvider>
  )
}
