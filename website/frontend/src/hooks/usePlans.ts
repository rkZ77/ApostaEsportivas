import { useEffect, useState } from 'react'
import api from '../services/api'

/*
 * Catálogo de planos, lido de GET /api/payments/plans.
 *
 * O preço vive no backend (routers/payments.py), que é quem cobra. Este hook
 * existe pra que nenhuma tela volte a escrever o valor à mão: era assim que o
 * JSON-LD acabou anunciando R$ 49,90 enquanto a cobrança era R$ 39,90, e que o
 * Checkout dizia "Economize 17%" num plano de 16%.
 *
 * Desde 12/09/2026 o catálogo tem dois eixos: o produto (tier) e o ciclo de
 * cobrança. São 8 planos, e a tela cruza os dois.
 */

export type PlanTier = 'base' | 'pro'

export interface Plan {
  id: string
  /** Produto: 'base' é o Pick IA, 'pro' é o Pick IA Pro. */
  tier: PlanTier
  tier_label: string
  /** Ciclo de cobrança: mensal, trimestral, semestral ou anual. */
  cycle: string
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
  { id: 'mensal_base',     tier: 'base', tier_label: 'Pick IA',     cycle: 'mensal',     label: 'Mensal',     title: 'Pick IA Mensal',         price: 29.90,  days: 30,  period: '1 mês',    months: 1,  price_per_month: 29.90, iso_period: 'P1M', savings: 0,      save_pct: 0 },
  { id: 'trimestral_base', tier: 'base', tier_label: 'Pick IA',     cycle: 'trimestral', label: 'Trimestral', title: 'Pick IA Trimestral',     price: 74.90,  days: 90,  period: '3 meses',  months: 3,  price_per_month: 24.97, iso_period: 'P3M', savings: 14.80,  save_pct: 16 },
  { id: 'semestral_base',  tier: 'base', tier_label: 'Pick IA',     cycle: 'semestral',  label: 'Semestral',  title: 'Pick IA Semestral',      price: 149.90, days: 180, period: '6 meses',  months: 6,  price_per_month: 24.98, iso_period: 'P6M', savings: 29.50,  save_pct: 16 },
  { id: 'anual_base',      tier: 'base', tier_label: 'Pick IA',     cycle: 'anual',      label: 'Anual',      title: 'Pick IA Anual',          price: 269.90, days: 365, period: '12 meses', months: 12, price_per_month: 22.49, iso_period: 'P1Y', savings: 88.90,  save_pct: 25 },
  { id: 'mensal',          tier: 'pro',  tier_label: 'Pick IA Pro', cycle: 'mensal',     label: 'Mensal',     title: 'Pick IA Pro Mensal',     price: 39.90,  days: 30,  period: '1 mês',    months: 1,  price_per_month: 39.90, iso_period: 'P1M', savings: 0,      save_pct: 0 },
  { id: 'trimestral',      tier: 'pro',  tier_label: 'Pick IA Pro', cycle: 'trimestral', label: 'Trimestral', title: 'Pick IA Pro Trimestral', price: 99.90,  days: 90,  period: '3 meses',  months: 3,  price_per_month: 33.30, iso_period: 'P3M', savings: 19.80,  save_pct: 17 },
  { id: 'semestral',       tier: 'pro',  tier_label: 'Pick IA Pro', cycle: 'semestral',  label: 'Semestral',  title: 'Pick IA Pro Semestral',  price: 199.90, days: 180, period: '6 meses',  months: 6,  price_per_month: 33.32, iso_period: 'P6M', savings: 39.50,  save_pct: 16 },
  { id: 'anual',           tier: 'pro',  tier_label: 'Pick IA Pro', cycle: 'anual',      label: 'Anual',      title: 'Pick IA Pro Anual',      price: 359.90, days: 365, period: '12 meses', months: 12, price_per_month: 29.99, iso_period: 'P1Y', savings: 118.90, save_pct: 25 },
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
  const byTier = (tier: PlanTier) => plans.filter(p => p.tier === tier)
  /** O plano de um produto num ciclo. É assim que a tela cruza os dois eixos. */
  const byTierCycle = (tier: PlanTier, cycle: string) =>
    plans.find(p => p.tier === tier && p.cycle === cycle)

  return {
    plans, loaded, byId, byTier, byTierCycle,
    /*
     * Os dois mensais são a régua de comparação da página de vendas: o preço
     * grande que aparece em cada coluna, e o "a partir de" da Home.
     */
    monthly: byTierCycle('pro', 'mensal') ?? FALLBACK[4],
    monthlyBase: byTierCycle('base', 'mensal') ?? FALLBACK[0],
  }
}

/** "R$ 39,90". Uma vírgula, sem centavos escondidos. */
export function fmtPlanPrice(v: number): string {
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}
