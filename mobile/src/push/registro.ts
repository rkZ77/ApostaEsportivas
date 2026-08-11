/**
 * Push · infraestrutura pronta, envio ainda não ligado (§13).
 *
 * O que existe aqui: permissão, canal Android e obtenção do token do
 * aparelho. O que NÃO existe: mandar esse token para o backend.
 *
 * O motivo é concreto. `POST /api/notifications/subscribe` grava uma
 * inscrição Web Push (`endpoint` + chaves `p256dh`/`auth` geradas pelo
 * Service Worker do site) na tabela `user_push_subscriptions`. Um app nativo
 * não produz nada disso -- ele tem um token opaco do Expo/FCM. Enfiar o
 * token nativo naquele formato sujaria a tabela que hoje entrega as
 * notificações do site, que funcionam e não podem quebrar por causa do app.
 *
 * O passo que falta, quando essa fase chegar: uma coluna/tabela para token
 * nativo e um envio via FCM no `notifications.py`, ao lado do webpush atual.
 * Nada disso é necessário para rodar o app em DEV, então fica de fora agora.
 */
import * as Device from 'expo-device'
import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'
import { cores } from '../theme/tokens'

/** Notificação recebida com o app aberto aparece na tela, como no site. */
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
})

/**
 * Pede permissão e devolve o token do aparelho, ou null se não der.
 *
 * Não lança: push é acessório · se falhar, o app continua inteiro. Também
 * não pede permissão sozinho na abertura -- o certo é chamar isto num
 * momento em que o usuário entenda o pedido (ex.: ao ativar alertas no
 * perfil), senão a permissão é negada e não volta mais.
 */
export async function obterTokenDePush(): Promise<string | null> {
  // Emulador não recebe push · em DEV isso é o caso normal, não um erro.
  if (!Device.isDevice) return null

  try {
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Picks',
        importance: Notifications.AndroidImportance.DEFAULT,
        lightColor: cores.accent,
      })
    }

    const { status: atual } = await Notifications.getPermissionsAsync()
    let status = atual
    if (status !== 'granted') {
      status = (await Notifications.requestPermissionsAsync()).status
    }
    if (status !== 'granted') return null

    const { data } = await Notifications.getExpoPushTokenAsync()
    return data
  } catch {
    return null
  }
}
