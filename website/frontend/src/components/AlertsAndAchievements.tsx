import { useEffect, useState } from 'react'
import { Bell, BellOff, BellRing, Trophy, Lock } from 'lucide-react'
import api from '../services/api'
import { Badge, Panel, PanelHead, Spinner } from './ui'

/*
 * Alertas e conquistas do usuário, na tela de Perfil.
 *
 * Ficam juntos porque são as duas coisas "sobre mim" que não cabem em nenhuma
 * outra tela, e porque as duas são leitura curta: separar em duas seções
 * distantes faria o usuário rolar atrás de dois blocos de cinco linhas.
 */

interface Alert {
  kind: string
  label: string
  enabled: boolean
  min_confidence: number | null
  min_ev: number | null
  configured: boolean
}

interface Achievement {
  code: string
  title: string
  desc: string
  goal: number
  current: number
  unlocked: boolean
}

function AlertRow({ alert, onToggle, onThreshold }: {
  alert: Alert
  onToggle: (enabled: boolean) => void
  onThreshold: (v: number) => void
}) {
  return (
    <div className="px-5 py-4 flex items-start gap-3">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-ink-1 font-medium">{alert.label}</p>

        {/* O limiar só faz sentido pro alerta de confiança, e só quando ligado */}
        {alert.kind === 'confidence' && alert.enabled && (
          <div className="flex items-center gap-2 mt-2.5">
            <input
              type="range"
              min={50} max={95} step={5}
              value={Math.round((alert.min_confidence ?? 0.7) * 100)}
              onChange={e => onThreshold(Number(e.target.value) / 100)}
              aria-label="Confiança mínima para o alerta"
              className="flex-1 max-w-[180px] accent-accent"
            />
            <span className="font-mono text-xs text-ink-2 tabular-nums w-9">
              {Math.round((alert.min_confidence ?? 0.7) * 100)}%
            </span>
          </div>
        )}
      </div>

      {/* Interruptor. Botão com aria-pressed em vez de checkbox estilizado:
          o estado fica correto pro leitor de tela sem input escondido. */}
      <button
        type="button"
        role="switch"
        aria-checked={alert.enabled}
        aria-label={`${alert.enabled ? 'Desligar' : 'Ligar'} alerta: ${alert.label}`}
        onClick={() => onToggle(!alert.enabled)}
        className={`relative w-10 h-6 rounded-full shrink-0 transition-colors duration-1 ease-smooth ${
          alert.enabled ? 'bg-accent' : 'bg-surface-3'
        }`}
      >
        <span
          className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform duration-1 ease-smooth ${
            alert.enabled ? 'translate-x-5' : 'translate-x-1'
          }`}
        />
      </button>
    </div>
  )
}

/** O que o Perfil sabe sobre push. Vem de fora porque o hook ja vive la e
 *  duplicar a inscricao criaria dois donos do mesmo estado. */
export interface PushInfo {
  supported: boolean
  vapidKey: string
  subscribed: boolean
  permission: string
  loading: boolean
  subscribe: () => void
  unsubscribe: () => void
}

export default function AlertsAndAchievements({ push }: { push?: PushInfo }) {
  const [alerts, setAlerts] = useState<Alert[] | null>(null)
  const [achievements, setAchievements] = useState<Achievement[] | null>(null)
  const [unlockedCount, setUnlockedCount] = useState(0)

  useEffect(() => {
    api.get('/personal/alerts')
      .then(r => setAlerts(r.data ?? []))
      .catch(() => setAlerts([]))
    api.get('/personal/achievements')
      .then(r => {
        setAchievements(r.data?.achievements ?? [])
        setUnlockedCount(r.data?.unlocked ?? 0)
      })
      .catch(() => setAchievements([]))
  }, [])

  const saveAlert = (kind: string, patch: Partial<Alert>) => {
    // otimista: o interruptor precisa responder no toque
    setAlerts(prev => prev?.map(a => a.kind === kind ? { ...a, ...patch } : a) ?? prev)
    const target = alerts?.find(a => a.kind === kind)
    if (!target) return
    const next = { ...target, ...patch }
    api.put('/personal/alerts', {
      kind,
      enabled: next.enabled,
      min_confidence: next.min_confidence,
      min_ev: next.min_ev,
    }).catch(() => {
      // devolve ao estado anterior se o servidor recusar
      setAlerts(prev => prev?.map(a => a.kind === kind ? target : a) ?? prev)
    })
  }

  return (
    <div className="space-y-6">

      <Panel>
        <PanelHead
          label={<span className="flex items-center gap-2"><BellRing className="w-3.5 h-3.5" />Notificações</span>}
          meta={alerts ? `${alerts.filter(a => a.enabled).length} ativos` : undefined}
        />
        {alerts === null ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : (
          <>
            <div className="divide-y divide-line/50">
              {/* Entrega e conteudo no mesmo painel. Eram duas secoes separadas
                  ("Ativar notificacoes" e "Alertas") que respondiam a mesma
                  pergunta pela metade: uma ligava o canal sem dizer o que
                  chega, a outra escolhia o que chega sem dizer por onde. */}
              {push?.supported && push.vapidKey !== '' && (
                <div className="flex items-center justify-between gap-4 px-5 py-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${push.subscribed ? 'bg-green-500/10' : 'bg-surface-2'}`}>
                      {push.subscribed
                        ? <Bell className="w-4 h-4 text-green-400" />
                        : <BellOff className="w-4 h-4 text-ink-3" />}
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-ink-1">Avisos no aparelho</p>
                      <p className="text-xs text-ink-3">
                        {push.subscribed
                          ? 'Ativos. O sino continua guardando tudo mesmo assim.'
                          : 'Sem isso os avisos ficam só no sino do site.'}
                      </p>
                    </div>
                  </div>
                  {push.permission === 'denied' ? (
                    <span className="text-xs text-ink-4 shrink-0">Bloqueado no navegador</span>
                  ) : (
                    <button
                      onClick={push.subscribed ? push.unsubscribe : push.subscribe}
                      disabled={push.loading}
                      className={`shrink-0 px-4 py-2 rounded-lg text-xs font-bold transition-colors disabled:opacity-40 ${
                        push.subscribed
                          ? 'bg-surface-2 text-ink-2 hover:bg-surface-3'
                          : 'bg-green-500 text-black hover:bg-green-400'
                      }`}
                    >
                      {push.loading ? '...' : push.subscribed ? 'Desativar' : 'Ativar'}
                    </button>
                  )}
                </div>
              )}
              {alerts.map(a => (
                <AlertRow
                  key={a.kind}
                  alert={a}
                  onToggle={enabled => saveAlert(a.kind, { enabled })}
                  onThreshold={v => saveAlert(a.kind, { min_confidence: v })}
                />
              ))}
            </div>
            <p className="px-5 py-3 border-t border-line text-[11px] text-ink-4 leading-relaxed">
              Tudo chega no sino do site, e também no aparelho se você tiver ativado acima.
            </p>
          </>
        )}
      </Panel>

      <Panel>
        <PanelHead
          label={<span className="flex items-center gap-2"><Trophy className="w-3.5 h-3.5" />Conquistas</span>}
          meta={achievements ? `${unlockedCount} de ${achievements.length}` : undefined}
        />
        {achievements === null ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : (
          <div className="grid sm:grid-cols-2 gap-px bg-line">
            {achievements.map(a => (
              <div key={a.code} className="bg-surface-0 px-5 py-4">
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <p className={`text-sm font-medium ${a.unlocked ? 'text-ink-1' : 'text-ink-3'}`}>
                    {a.title}
                  </p>
                  {a.unlocked
                    ? <Badge tone="green">Feito</Badge>
                    : <Lock className="w-3.5 h-3.5 text-ink-4 shrink-0 mt-0.5" />}
                </div>
                <p className="text-[11px] text-ink-4 leading-relaxed mb-2.5">{a.desc}</p>

                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1 bg-surface-2 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${a.unlocked ? 'bg-accent' : 'bg-ink-4'}`}
                      style={{ width: `${Math.min(100, (a.current / a.goal) * 100)}%` }}
                    />
                  </div>
                  <span className="font-mono text-[10px] text-ink-4 tabular-nums shrink-0">
                    {a.current}/{a.goal}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}
