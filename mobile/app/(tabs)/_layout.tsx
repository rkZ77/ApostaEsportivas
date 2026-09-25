/**
 * Navegação principal: cinco abas fixas na base.
 *
 * Barra inferior em vez do menu lateral do site porque no celular o polegar
 * alcança a base da tela, não o topo. Cinco é o teto: acima disso os alvos
 * ficam estreitos demais para o toque.
 */
import { Tabs } from 'expo-router'
import { Activity, Home, ListChecks, Target, User } from 'lucide-react-native'
import { StyleSheet } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { cores, familia, fonte, peso } from '../../src/theme/tokens'

export default function TabsLayout() {
  /* A altura soma a área segura de baixo (indicador de início do iPhone,
     barra de gestos do Android). Com a altura fixa que havia aqui, o nome da
     aba ficava espremido pelo indicador e saía cortado. */
  const insets = useSafeAreaInsets()
  const baixo = Math.max(insets.bottom, 8)

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: cores.surface0 },
        headerTintColor: cores.ink1,
        headerShadowVisible: false,
        headerTitleStyle: { fontFamily: familia(peso.bold) },
        sceneStyle: { backgroundColor: cores.surface0 },
        tabBarStyle: {
          backgroundColor: cores.surface1,
          borderTopColor: cores.line,
          borderTopWidth: StyleSheet.hairlineWidth * 2,
          height: 58 + baixo,
          paddingBottom: baixo,
          paddingTop: 6,
        },
        tabBarActiveTintColor: cores.accent,
        tabBarInactiveTintColor: cores.ink4,
        tabBarLabelStyle: { fontSize: fonte.xs, fontFamily: familia(peso.semi) },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: 'Início', tabBarIcon: ({ color, size }) => <Home size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="picks"
        options={{ title: 'Picks', tabBarIcon: ({ color, size }) => <Target size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="ao-vivo"
        options={{ title: 'Ao vivo', tabBarIcon: ({ color, size }) => <Activity size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="minhas-apostas"
        options={{ title: 'Apostas', tabBarIcon: ({ color, size }) => <ListChecks size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="perfil"
        options={{ title: 'Perfil', tabBarIcon: ({ color, size }) => <User size={size} color={color} /> }}
      />
    </Tabs>
  )
}
