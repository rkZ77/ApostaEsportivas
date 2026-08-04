import { useEffect, useState } from 'react'
import api from '../services/api'

/*
 * Catálogo de planos, lido de GET /api/payments/plans.
 *
 * O preço vive no backend (routers/payments.py), que é quem cobra. Este hook
 * existe pra que nenhuma tela volte a escrever o valor à mão: era assim que o
 * JSON-LD acabou anunciando R$ 49,90 enquanto a cobrança era R$ 39,90, e que o
 * Checkout dizia "Economize 17%" num plano de 16%.
 */

export interface Plan {
  id: string
  label: string
  title: string
  price: number
  days: number
  period: string
  months: number
  price_per_month: number
  iso_period: string
  savings: number
  save_pct: number
}

/*
 * Reserva usada só enquanto a resposta não chega, ou se a chamada falhar.
 *
 * Não é uma segunda fonte de verdade: serve pra página de vendas não abrir com
 * buraco no lugar do preço. Se divergir do backend, o backend é que está certo,
 * e o valor correto entra sozinho quando a resposta chega.
 */
const FALLBACK: Plan[] = [
  { id: 'mensal',     label: 'Mensal',     title: 'Plano Picks Mensal',     price: 39.90,  days: 30,  period: '1 mês',    months: 1,  price_per_month: 39.90, iso_period: 'P1M', savings: 0,      save_pct: 0 },
  { id: 'trimestral', label: 'Trimestral', title: 'Plano Picks Trimestral', price: 99.90,  days: 90,  period: '3 meses',  months: 3,  price_per_month: 33.30, iso_period: 'P3M', savings: 19.80,  save_pct: 17 },
  { id: 'semestral',  label: 'Semestral',  title: 'Plano Picks Semestral',  price: 199.90, days: 180, period: '6 meses',  months: 6,  price_per_month: 33.32, iso_period: 'P6M', savings: 39.50,  save_pct: 16 },
  { id: 'anual',      label: 'Anual',      title: 'Plano Picks Anual',      price: 359.90, days: 365, period: '12 meses', months: 12, price_per_month: 29.99, iso_period: 'P1Y', savings: 118.90, save_pct: 25 },
]

export function usePlans() {
  const [plans, setPlans] = useState<Plan[]>(FALLBACK)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let alive = true
    api.get('/payments/plans')
      .then(r => {
        if (!alive) return
        const list = r.data?.plans
        if (Array.isArray(list) && list.length > 0) setPlans(list)
      })
      .catch(() => { /* segue com a reserva */ })
      .finally(() => { if (alive) setLoaded(true) })
    return () => { alive = false }
  }, [])

  const byId = (id: string) => plans.find(p => p.id === id)

  return { plans, loaded, byId, monthly: byId('mensal') ?? FALLBACK[0] }
}

/** "R$ 39,90". Uma vírgula, sem centavos escondidos. */
export function fmtPlanPrice(v: number): string {
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}
