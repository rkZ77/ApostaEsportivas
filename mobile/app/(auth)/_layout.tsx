import { Stack } from 'expo-router'
import { cores } from '../../src/theme/tokens'

export default function AuthLayout() {
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: cores.surface0 },
        headerTintColor: cores.ink1,
        headerShadowVisible: false,
        contentStyle: { backgroundColor: cores.surface0 },
      }}
    >
      <Stack.Screen name="login" options={{ headerShown: false }} />
      <Stack.Screen name="cadastro" options={{ title: 'Criar conta' }} />
      <Stack.Screen name="esqueci-senha" options={{ title: 'Recuperar senha' }} />
    </Stack>
  )
}
