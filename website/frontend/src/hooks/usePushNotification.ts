import { useState, useEffect } from 'react'
import api from '../services/api'

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  return new Uint8Array([...raw].map(c => c.charCodeAt(0)))
}

export function usePushNotification() {
  const [supported, setSupported]   = useState(false)
  const [permission, setPermission] = useState<NotificationPermission>('default')
  const [subscribed, setSubscribed] = useState(false)
  const [loading, setLoading]       = useState(false)
  const [vapidKey, setVapidKey]     = useState('')

  useEffect(() => {
    const ok =
      'serviceWorker' in navigator &&
      'PushManager' in window &&
      'Notification' in window
    setSupported(ok)
    if (!ok) return

    setPermission(Notification.permission)

    api.get('/notifications/vapid-public-key')
      .then(r => setVapidKey(r.data.public_key))
      .catch(() => {})

    navigator.serviceWorker.ready.then(reg =>
      reg.pushManager.getSubscription().then(sub => setSubscribed(!!sub))
    ).catch(() => {})
  }, [])

  const subscribe = async () => {
    if (!vapidKey || !supported) return
    setLoading(true)
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidKey),
      })
      await api.post('/notifications/subscribe', sub.toJSON())
      setSubscribed(true)
      setPermission(Notification.permission)
    } catch { }
    finally { setLoading(false) }
  }

  const unsubscribe = async () => {
    setLoading(true)
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        await sub.unsubscribe()
        await api.delete('/notifications/subscribe')
      }
      setSubscribed(false)
    } catch { }
    finally { setLoading(false) }
  }

  return { supported, permission, subscribed, loading, vapidKey, subscribe, unsubscribe }
}
