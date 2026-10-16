import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import api from '../services/api'

/*
 * Faixa no topo do painel quando a revisão por IA de algum motor está falhando.
 *
 * A IA tem papel central na decisão, e em modo enforce um pick sem parecer não
 * sai. Sem esta faixa, "sem crédito no provedor" só aparecia no terminal de
 * quem rodou o motor, e o sintoma no site era um dia sem pick e sem motivo.
 *
 * Silenciosa quando está tudo certo: nenhuma falha, nenhuma faixa.
 */

interface Alerta {
  pipeline: string
  provider: string
  model: string
  mode: string
  erro_tipo: string
  erro: string | null
  acao: string
  falhas_24h: number
  quando: string | null
}

const NOME_DO_MOTOR: Record<string, string> = {
  vip: 'Premium',
  dica: 'Dica do Dia',
  multipla: 'Múltipla',
  bingo: 'Bingo',
  alavancagem: 'Alavancagem',
  faltas: 'Pick Falta',
  boost: 'Pick Boost',
  player_stats: 'Pick Jogador',
  live: 'Ao Vivo',
}

function horario(iso: string | null): string {
  if (!iso) return ''
  // Hora lida do texto, sem `new Date`: o banco grava sem fuso.
  const [data, hora] = iso.split('T')
  const [, mes, dia] = data.split('-')
  return `${dia}/${mes} às ${(hora || '').slice(0, 5)}`
}

export default function AdminAlertaIA() {
  const [alertas, setAlertas] = useState<Alerta[]>([])

  useEffect(() => {
    let vivo = true
    const buscar = async () => {
      try {
        const { data } = await api.get('/admin/ia/alertas')
        if (vivo) setAlertas(Array.isArray(data?.alertas) ? data.alertas : [])
      } catch {
        // Falha ao consultar o alerta não vira outro alerta: a faixa some.
        if (vivo) setAlertas([])
      }
    }
    buscar()
    const id = setInterval(buscar, 120_000)
    return () => { vivo = false; clearInterval(id) }
  }, [])

  if (!alertas.length) return null

  return (
    <div className="mb-4 rounded-md border border-red-500/40 bg-red-500/10 p-3 sm:p-4" role="alert">
      <div className="flex items-center gap-2 text-sm font-semibold text-red-400">
        <AlertTriangle size={16} aria-hidden />
        Revisão por IA com falha
      </div>
      <ul className="mt-2 space-y-2">
        {alertas.map(a => (
          <li key={`${a.pipeline}-${a.provider}`} className="text-xs sm:text-sm text-ink-2">
            <span className="font-semibold text-ink-1">{NOME_DO_MOTOR[a.pipeline] || a.pipeline}</span>
            {' '}({a.provider === 'openai' ? 'OpenAI' : 'Anthropic'}, modo {a.mode === 'enforce' ? 'decisivo, sem pick até resolver' : 'observação'}):{' '}
            {a.acao}
            <span className="block text-ink-3">
              {a.falhas_24h} falha{a.falhas_24h === 1 ? '' : 's'} nas últimas 24h. Última em {horario(a.quando)}.
              {a.erro ? ` Erro: ${a.erro}` : ''}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
