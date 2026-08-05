import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, BellOff, Eye, EyeOff } from 'lucide-react'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import PageShell from '../components/PageShell'
import { Spinner } from '../components/ui'
import AlertsAndAchievements from '../components/AlertsAndAchievements'
import Avatar from '../components/Avatar'
import { usePushNotification } from '../hooks/usePushNotification'
import { maskPhone } from '../utils/format'
import { getPasswordStrength } from '../utils/passwordStrength'

interface ReferralData {
  referral_code: string
  referral_link: string
  total_indicated: number
  total_converted: number
  days_earned: number
}

function displayPhone(raw: string): string {
  if (!raw) return ''
  const digits = raw.startsWith('+55') ? raw.slice(3) : raw.replace(/\D/g, '')
  return maskPhone(digits)
}

export default function Profile() {
  const { user, updateUser } = useAuth()
  const navigate = useNavigate()

  const [name, setName]             = useState(user?.name ?? '')
  const [username, setUsername]     = useState('')
  const [phone, setPhone]           = useState(displayPhone(user?.phone ?? ''))
  // Sincroniza phone quando refreshUser() completar (login não retornava phone antes)
  useEffect(() => { if (user?.phone) setPhone(displayPhone(user.phone)) }, [user?.phone])
  const [cpf, setCpf]               = useState('')
  const [loading, setLoading]       = useState(false)
  const [successMsg, setSuccessMsg] = useState('')
  const [error, setError]           = useState('')
  const [meData, setMeData]         = useState<any>(null)

  const [avatarUploading, setAvatarUploading] = useState(false)
  const [avatarPreview, setAvatarPreview]     = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const push = usePushNotification()

  const [referral, setReferral]       = useState<ReferralData | null>(null)
  const [referralLoaded, setReferralLoaded] = useState(false)
  const [referralCopied, setReferralCopied] = useState(false)

  const [showPasswordChange, setShowPasswordChange] = useState(false)
  const [pwStep, setPwStep]                         = useState<'form' | 'code'>('form')
  const [currentPassword, setCurrentPassword]       = useState('')
  const [newPassword, setNewPassword]               = useState('')
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('')
  const [pwCode, setPwCode]                         = useState('')
  const [showCurrentPw, setShowCurrentPw]           = useState(false)
  const [showNewPw, setShowNewPw]                   = useState(false)
  const [passwordChanging, setPasswordChanging]     = useState(false)
  const [passwordChangeErr, setPasswordChangeErr]   = useState('')
  const [passwordChanged, setPasswordChanged]       = useState(false)

  const [loggingOutOthers, setLoggingOutOthers] = useState(false)
  const [loggedOutOthers, setLoggedOutOthers]   = useState(false)

  const [emailResending, setEmailResending] = useState(false)
  const [emailResent, setEmailResent]       = useState(false)
  const [emailCooldown, setEmailCooldown]   = useState(0)
  const [showEmailChange, setShowEmailChange] = useState(false)
  const [newEmail, setNewEmail]             = useState('')
  const [emailPassword, setEmailPassword]   = useState('')
  const [emailChanging, setEmailChanging]   = useState(false)
  const [emailChangeErr, setEmailChangeErr] = useState('')
  const [emailChanged, setEmailChanged]     = useState('')

  useEffect(() => {
    if (emailCooldown <= 0) return
    const t = setTimeout(() => setEmailCooldown(c => c - 1), 1000)
    return () => clearTimeout(t)
  }, [emailCooldown])

  useEffect(() => {
    api.get('/auth/referral').then(r => { setReferral(r.data); setReferralLoaded(true) }).catch(() => setReferralLoaded(true))
    api.get('/auth/me').then(r => { setMeData(r.data); setUsername(r.data.username ?? '') }).catch(() => {})
  }, [])

  const handleResendEmail = async () => {
    setEmailResending(true)
    try {
      await api.post('/auth/resend-verification')
      setEmailResent(true)
      setEmailCooldown(60)
    } catch { /* silent */ }
    finally { setEmailResending(false) }
  }

  const handleChangeEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    setEmailChangeErr('')
    setEmailChanging(true)
    try {
      const { data } = await api.post('/auth/change-email', { new_email: newEmail, current_password: emailPassword })
      updateUser({ email: data.email, email_verified: false })
      setEmailChanged(data.email)
      setShowEmailChange(false)
      setEmailResent(true)
      setEmailCooldown(60)
      setNewEmail('')
      setEmailPassword('')
    } catch (err: any) {
      setEmailChangeErr(err?.response?.data?.detail || 'Erro ao alterar e-mail')
    } finally {
      setEmailChanging(false)
    }
  }

  const handleRequestPasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordChangeErr('')
    if (newPassword !== newPasswordConfirm) { setPasswordChangeErr('As senhas não coincidem'); return }
    const { score } = getPasswordStrength(newPassword)
    if (score < 3) { setPasswordChangeErr('Senha deve ter no mínimo 10 caracteres, 1 letra maiúscula e 1 número'); return }
    setPasswordChanging(true)
    try {
      await api.post('/auth/profile/password/request', { current_password: currentPassword, new_password: newPassword })
      setPwStep('code')
    } catch (err: any) {
      setPasswordChangeErr(err?.response?.data?.detail || 'Erro ao solicitar troca de senha')
    } finally {
      setPasswordChanging(false)
    }
  }

  const resetPasswordChangeState = () => {
    setShowPasswordChange(false)
    setPwStep('form')
    setPasswordChangeErr('')
    setCurrentPassword(''); setNewPassword(''); setNewPasswordConfirm(''); setPwCode('')
  }

  const handleConfirmPasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordChangeErr('')
    setPasswordChanging(true)
    try {
      await api.post('/auth/profile/password/confirm', { code: pwCode })
      setPasswordChanged(true)
      resetPasswordChangeState()
      setTimeout(() => setPasswordChanged(false), 3000)
    } catch (err: any) {
      setPasswordChangeErr(err?.response?.data?.detail || 'Código inválido ou expirado')
    } finally {
      setPasswordChanging(false)
    }
  }

  const handleLogoutOtherSessions = async () => {
    setLoggingOutOthers(true)
    try {
      await api.post('/auth/logout-other-sessions')
      setLoggedOutOthers(true)
      setTimeout(() => setLoggedOutOthers(false), 3000)
    } catch { /* silent */ }
    finally { setLoggingOutOthers(false) }
  }

  const copyReferralLink = () => {
    if (!referral) return
    navigator.clipboard.writeText(referral.referral_link).then(() => {
      setReferralCopied(true)
      setTimeout(() => setReferralCopied(false), 2000)
    })
  }

  const handleAvatarClick = () => fileInputRef.current?.click()

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // Preview local imediato
    const reader = new FileReader()
    reader.onload = ev => setAvatarPreview(ev.target?.result as string)
    reader.readAsDataURL(file)

    setAvatarUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const { data } = await api.post('/auth/avatar', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      updateUser({ avatar_url: data.avatar_url })
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao enviar foto')
      setAvatarPreview(null)
    } finally {
      setAvatarUploading(false)
      e.target.value = ''
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(''); setSuccessMsg('')

    const body: Record<string, string> = {}
    if (name !== user?.name)                         body.name = name
    if (username !== (meData?.username ?? ''))       body.username = username
    if (phone !== (user?.phone ?? ''))               body.phone = phone
    if (cpf.trim())                                  body.cpf = cpf.trim()

    if (!Object.keys(body).length) { setError('Nenhuma alteração detectada'); return }

    setLoading(true)
    try {
      const { data } = await api.put('/auth/profile', body)
      updateUser(data)
      if (data.trial_activated) {
        setSuccessMsg('CPF verificado! 2 dias de VIP gratuito ativados!')
        setMeData((prev: any) => ({ ...prev, has_cpf: true, trial_used: true }))
      } else {
        setSuccessMsg('Perfil atualizado!')
      }
      setCpf('')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao atualizar')
    } finally {
      setLoading(false)
    }
  }

  const planBadge: Record<string, string> = {
    free: 'badge-free', vip: 'badge-vip', admin: 'badge-admin',
  }

  // Countdown ao vivo para expiração do plano
  const [countdown, setCountdown] = useState('')
  useEffect(() => {
    if (!user?.expires_at || user.plan === 'free' || user.plan === 'admin') {
      setCountdown('')
      return
    }
    const tick = () => {
      const diff = new Date(user.expires_at!).getTime() - Date.now()
      if (isNaN(diff) || diff <= 0) { setCountdown('Expirado'); return }
      const d = Math.floor(diff / 86400000)
      const h = Math.floor((diff % 86400000) / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      const s = Math.floor((diff % 60000) / 1000)
      setCountdown(`${d}d ${h}h ${m.toString().padStart(2,'0')}m ${s.toString().padStart(2,'0')}s`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [user?.expires_at, user?.plan])

  const planMeta: Record<string, { label: string; color: string }> = {
    free:  { label: 'FREE',  color: 'text-ink-2' },
    trial: { label: 'TRIAL', color: 'text-amber-400' },
    vip:   { label: 'VIP',   color: 'text-yellow-400' },
    admin: { label: 'ADMIN', color: 'text-purple-400' },
  }
  const pm = planMeta[user?.plan ?? 'free'] ?? planMeta.free

  const currentAvatar = avatarPreview ?? user?.avatar_url ?? null

  return (
    <PageShell
      title="Meu Perfil"
      description="Gerencie suas informações, senha, avatar e preferências de conta."
      noindex
      width="narrow"
      bar={{ back: true, title: 'Meu Perfil', sub: 'Gerencie suas informações e preferências' }}
      mainClassName="space-y-6"
    >
        {/* Info atual + upload de avatar */}
        <div className="card p-5 flex items-center gap-4">
          <div className="relative group cursor-pointer shrink-0" onClick={handleAvatarClick}>
            {user?.name && (
              <Avatar name={user.name} imageUrl={currentAvatar} size="lg" />
            )}
            <div className="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
              {avatarUploading
                ? <Spinner size="sm" className="border-white border-t-transparent" />
                : <svg className="w-5 h-5 text-ink-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
              }
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={handleAvatarChange}
            />
          </div>

          <div className="flex-1 min-w-0">
            <p className="text-ink-1 font-bold truncate">{user?.name}</p>
            {meData?.username && <p className="text-green-500 text-xs font-semibold">@{meData.username}</p>}
            <p className="text-ink-3 text-xs truncate mt-0.5">{user?.email}</p>
            <p className="text-ink-4 text-xs mt-1.5 flex items-center gap-1">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
              </svg>
              Toque na foto para trocar
            </p>
          </div>
          <span className={planBadge[user?.plan ?? 'free'] ?? 'badge-free'}>
            {user?.plan === 'vip' ? 'VIP' : user?.plan === 'trial' ? 'TESTE' : user?.plan === 'admin' ? 'ADMIN' : 'FREE'}
          </span>
        </div>

        {/* Assinatura */}
        <div className="card p-5">
          <p className="text-xs text-ink-3 font-semibold mb-4">Assinatura</p>
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="text-ink-2 text-sm">Status atual:</span>
                <span className={`text-sm font-black ${pm.color}`}>{pm.label}</span>
              </div>
              {countdown && (
                <p className="text-ink-2 text-sm">
                  Expira em <span className="font-bold text-ink-1 tabular-nums">{countdown}</span>
                </p>
              )}
              {user?.plan === 'free' && (
                <p className="text-ink-3 text-xs">Faça upgrade para acessar picks VIP</p>
              )}
            </div>
            {(user?.plan === 'free' || user?.plan === 'trial') && (
              <button
                type="button"
                onClick={() => navigate('/planos')}
                className="shrink-0 bg-green-600 hover:bg-green-500 text-ink-1 font-bold text-sm px-5 py-2.5 rounded-md transition-colors"
              >
                Assinar
              </button>
            )}
            {user?.plan === 'vip' && (
              <span className="shrink-0 text-xs font-bold text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-3 py-1.5 rounded-lg">
                Ativo ✓
              </span>
            )}
          </div>
        </div>

        {/* Formulário */}
        <form onSubmit={handleSubmit} className="card p-6 space-y-5">
          <p className="text-xs text-ink-3 font-semibold">Informações pessoais</p>
          <div>
            <label className="text-xs text-ink-3 block mb-1.5">Nome completo</label>
            <input className="input w-full" value={name} onChange={e => setName(e.target.value)} required />
          </div>

          <div>
            <label className="text-xs text-ink-3 block mb-1.5">Nome de usuário <span className="text-ink-4 font-normal">(para login)</span></label>
            <input className="input w-full" value={username}
              onChange={e => setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
              placeholder="seu_usuario" maxLength={20} />
            <p className="text-xs text-ink-4 mt-1">3–20 caracteres · letras minúsculas, números e _</p>
          </div>

          <div>
            <label className="text-xs text-ink-3 block mb-1.5">WhatsApp <span className="text-ink-4 font-normal">(opcional)</span></label>
            <input className="input w-full" value={phone} onChange={e => setPhone(maskPhone(e.target.value))} placeholder="(11) 99999-9999" type="tel" inputMode="numeric" />
          </div>

          {!meData?.has_cpf && (
            <div>
              <label className="text-xs text-ink-3 block mb-1.5">
                CPF <span className="text-ink-4">(necessário para ativar o teste gratuito)</span>
              </label>
              <input className="input w-full" value={cpf} onChange={e => setCpf(e.target.value)}
                placeholder="000.000.000-00" />
              {user?.plan === 'free' && !meData?.trial_used && (
                <p className="text-xs text-green-500 mt-1">
                  Adicione seu CPF e salve para receber 2 dias de VIP grátis.
                </p>
              )}
            </div>
          )}

          <hr className="border-line" />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-ink-3 font-semibold">Senha</p>
              <p className="text-xs text-ink-4 mt-0.5">
                {passwordChanged ? <span className="text-green-400">Senha alterada!</span> : 'Troque sua senha atual'}
              </p>
            </div>
            {!showPasswordChange && (
              <button
                type="button"
                onClick={() => setShowPasswordChange(true)}
                className="text-xs text-blue-400 hover:text-blue-300 transition-colors font-semibold border border-blue-400/20 hover:border-blue-400/40 bg-blue-400/5 px-3 py-2 rounded-lg"
              >
                Alterar senha
              </button>
            )}
          </div>

          {showPasswordChange && pwStep === 'form' && (
            <div className="space-y-3">
              <div className="relative">
                <input
                  type={showCurrentPw ? 'text' : 'password'}
                  value={currentPassword}
                  onChange={e => setCurrentPassword(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') e.preventDefault() }}
                  placeholder="Senha atual"
                  autoComplete="current-password"
                  required
                  className="input w-full pr-10 text-sm"
                />
                <button type="button" onClick={() => setShowCurrentPw(v => !v)}
                  aria-label={showCurrentPw ? 'Ocultar senha' : 'Mostrar senha'}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink-2 transition-colors">
                  {showCurrentPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <div className="relative">
                <input
                  type={showNewPw ? 'text' : 'password'}
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') e.preventDefault() }}
                  placeholder="Nova senha (mínimo 10 caracteres)"
                  autoComplete="new-password"
                  required
                  className="input w-full pr-10 text-sm"
                />
                <button type="button" onClick={() => setShowNewPw(v => !v)}
                  aria-label={showNewPw ? 'Ocultar senha' : 'Mostrar senha'}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink-2 transition-colors">
                  {showNewPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {newPassword.length > 0 && (() => {
                const { score, checks } = getPasswordStrength(newPassword)
                const barColors = ['bg-red-500', 'bg-yellow-400', 'bg-green-500']
                const labels    = ['Fraca', 'Boa', 'Forte']
                const color     = barColors[score - 1] ?? 'bg-surface-3'
                const label     = score > 0 ? labels[score - 1] : ''
                return (
                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5">
                      {[1, 2, 3].map(i => (
                        <div key={i} className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${i <= score ? color : 'bg-surface-2'}`} />
                      ))}
                      {label && <span className={`text-[11px] font-semibold ml-1 shrink-0 ${color.replace('bg-', 'text-')}`}>{label}</span>}
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                      {checks.map(c => (
                        <div key={c.label} className="flex items-center gap-1.5">
                          <span className={`text-[10px] ${c.ok ? 'text-green-500' : 'text-ink-4'}`}>{c.ok ? '✓' : '○'}</span>
                          <span className={`text-[11px] ${c.ok ? 'text-ink-2' : 'text-ink-4'}`}>{c.label}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })()}
              <input
                type={showNewPw ? 'text' : 'password'}
                value={newPasswordConfirm}
                onChange={e => setNewPasswordConfirm(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') e.preventDefault() }}
                placeholder="Confirme a nova senha"
                autoComplete="new-password"
                required
                className="input w-full text-sm"
              />
              {passwordChangeErr && <p className="text-red-400 text-xs">{passwordChangeErr}</p>}
              <div className="flex gap-2">
                <button type="button" onClick={handleRequestPasswordChange} disabled={passwordChanging}
                  className="flex-1 py-2.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-ink-1 font-bold text-sm transition-colors">
                  {passwordChanging ? 'Enviando…' : 'Enviar código de confirmação'}
                </button>
                <button type="button" onClick={resetPasswordChangeState}
                  className="px-4 py-2.5 rounded-md border border-line-strong text-ink-2 text-sm hover:border-ink-4 transition-colors">
                  Cancelar
                </button>
              </div>
              <button type="button" onClick={() => navigate('/forgot-password')}
                className="text-xs text-ink-4 hover:text-ink-2 transition-colors underline">
                Esqueceu a senha atual? Redefinir por e-mail
              </button>
            </div>
          )}

          {showPasswordChange && pwStep === 'code' && (
            <div className="space-y-3">
              <p className="text-xs text-ink-3">
                Enviamos um código de 6 dígitos pra <span className="text-ink-2 font-semibold">{user?.email}</span>. Ele expira em 15 minutos.
              </p>
              <input
                type="text"
                inputMode="numeric"
                value={pwCode}
                onChange={e => setPwCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                onKeyDown={e => { if (e.key === 'Enter') e.preventDefault() }}
                placeholder="000000"
                maxLength={6}
                required
                className="input w-full text-center text-lg font-bold tracking-widest"
              />
              {passwordChangeErr && <p className="text-red-400 text-xs">{passwordChangeErr}</p>}
              <div className="flex gap-2">
                <button type="button" onClick={handleConfirmPasswordChange} disabled={passwordChanging || pwCode.length !== 6}
                  className="flex-1 py-2.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-ink-1 font-bold text-sm transition-colors">
                  {passwordChanging ? 'Confirmando…' : 'Confirmar troca de senha'}
                </button>
                <button type="button" onClick={resetPasswordChangeState}
                  className="px-4 py-2.5 rounded-md border border-line-strong text-ink-2 text-sm hover:border-ink-4 transition-colors">
                  Cancelar
                </button>
              </div>
              <button type="button" onClick={() => setPwStep('form')}
                className="text-xs text-ink-4 hover:text-ink-2 transition-colors underline">
                Voltar
              </button>
            </div>
          )}

          {error      && <p className="text-red-400 text-xs">{error}</p>}
          {successMsg && <p className="text-green-400 text-xs">{successMsg}</p>}

          <div className="flex gap-3 pt-2">
            <button type="submit" disabled={loading} className="btn-primary flex-1 py-3">
              {loading ? 'Salvando...' : 'Salvar alterações'}
            </button>
            <button type="button" onClick={() => navigate(-1)} className="btn-ghost flex-1 py-3 text-sm">
              Cancelar
            </button>
          </div>
        </form>

        {/* Sessão */}
        <div className="card p-6 space-y-4">
          <div>
            <h2 className="text-sm font-bold text-ink-1">Sessão</h2>
            <p className="text-ink-3 text-xs mt-0.5">Você só pode estar logado em 1 dispositivo por vez</p>
          </div>
          {meData?.last_login_device && (
            <p className="text-sm text-ink-2">
              Último login: <span className="font-semibold text-ink-1">{meData.last_login_device}</span>
              {meData.last_login_at && (
                <span className="text-ink-3">
                  {' · '}
                  {new Date(meData.last_login_at).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
            </p>
          )}
          <button
            type="button"
            onClick={handleLogoutOtherSessions}
            disabled={loggingOutOthers}
            className="w-full py-2.5 rounded-md border border-line-strong hover:border-ink-4 text-ink-2 hover:text-ink-1 text-xs font-semibold transition-colors disabled:opacity-50"
          >
            {loggingOutOthers ? 'Encerrando…' : loggedOutOthers ? 'Sessão encerrada!' : 'Encerrar outras sessões'}
          </button>
          <p className="text-ink-4 text-xs">Use isso se suspeitar que esqueceu logado em outro aparelho.</p>
        </div>

        {/* E-mail e verificação.
            Com o e-mail pendente o cartão ganha contorno âmbar: é aqui que o
            ponto de atenção do avatar (ver Navbar) desemboca, e sem destaque o
            usuário chegaria numa tela cheia de cartões iguais sem saber qual
            deles pediu a visita. */}
        <div className={`card p-6 space-y-4 ${user?.email_verified === false ? 'border-yellow-400/30' : ''}`}>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-ink-1">E-mail</h2>
              <p className="text-ink-3 text-xs mt-0.5">Verificação e alteração</p>
            </div>
            {user?.email_verified
              ? <span className="text-xs font-bold text-green-400 bg-green-400/10 border border-green-400/20 px-2.5 py-1 rounded-lg">Verificado ✓</span>
              : <span className="text-xs font-bold text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-2.5 py-1 rounded-lg">Não verificado</span>
            }
          </div>

          <p className="text-sm text-ink-2 font-medium">{emailChanged || user?.email}</p>

          {!user?.email_verified && (
            <div className="space-y-3">
              {emailResent && (
                <p className="text-green-400 text-xs font-semibold">E-mail enviado! Verifique também a pasta de spam.</p>
              )}
              <div className="flex gap-2">
                <button
                  onClick={handleResendEmail}
                  disabled={emailResending || emailCooldown > 0}
                  className="flex-1 py-2.5 rounded-md border border-line-strong hover:border-ink-4 text-ink-2 hover:text-ink-1 text-xs font-semibold transition-colors disabled:opacity-50"
                >
                  {emailResending ? 'Enviando…' : emailCooldown > 0 ? `Reenviar em ${emailCooldown}s` : 'Reenviar confirmação'}
                </button>
                {!showEmailChange && (
                  <button
                    onClick={() => setShowEmailChange(true)}
                    className="flex-1 py-2.5 rounded-md border border-blue-500/30 hover:border-blue-400/50 text-blue-400 hover:text-blue-300 text-xs font-semibold transition-colors"
                  >
                    Alterar e-mail
                  </button>
                )}
              </div>

              {showEmailChange && (
                <form onSubmit={handleChangeEmail} className="space-y-2">
                  <input
                    type="email"
                    value={newEmail}
                    onChange={e => setNewEmail(e.target.value)}
                    placeholder="novo@email.com"
                    required
                    className="input w-full text-sm"
                  />
                  <input
                    type="password"
                    value={emailPassword}
                    onChange={e => setEmailPassword(e.target.value)}
                    placeholder="Confirme sua senha atual"
                    required
                    className="input w-full text-sm"
                  />
                  {emailChangeErr && <p className="text-red-400 text-xs">{emailChangeErr}</p>}
                  <div className="flex gap-2">
                    <button type="submit" disabled={emailChanging}
                      className="flex-1 py-2.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-ink-1 font-bold text-sm transition-colors">
                      {emailChanging ? 'Salvando…' : 'Salvar e reenviar'}
                    </button>
                    <button type="button" onClick={() => { setShowEmailChange(false); setEmailChangeErr(''); setEmailPassword('') }}
                      className="px-4 py-2.5 rounded-md border border-line-strong text-ink-2 text-sm hover:border-ink-4 transition-colors">
                      Cancelar
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}
        </div>

        {/* Notificacoes push */}
        {push.supported && push.vapidKey !== '' && (
          <div className="card p-5">
            <p className="text-xs text-ink-3 font-semibold mb-3">Notificações</p>
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0">
                <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${push.subscribed ? 'bg-green-500/10' : 'bg-surface-2'}`}>
                  {push.subscribed
                    ? <Bell className="w-4 h-4 text-green-400" />
                    : <BellOff className="w-4 h-4 text-ink-3" />}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink-1">
                    {push.subscribed ? 'Notificações ativas' : 'Ativar notificações'}
                  </p>
                  <p className="text-xs text-ink-3 truncate">
                    {push.subscribed
                      ? 'Aviso quando os picks do dia forem publicados'
                      : 'Receba aviso quando os picks do dia saírem'}
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
          </div>
        )}

        {/* Seção de Indicações */}
        <div className="card p-6 space-y-4">
          <div>
            <h2 className="text-sm font-bold text-ink-1">Programa de Indicações</h2>
            <p className="text-ink-3 text-xs mt-0.5">Indique amigos e ganhe 1 dia VIP por cada conversão</p>
          </div>

          {referral ? (
            <>
              <div>
                <p className="text-xs text-ink-3 mb-1.5">Seu link de indicação</p>
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-surface-1 border border-line-strong rounded-lg px-3 py-2 text-xs text-ink-2 font-mono truncate select-all">
                    {referral.referral_link}
                  </div>
                  <button
                    onClick={copyReferralLink}
                    className={`shrink-0 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                      referralCopied ? 'bg-green-500/20 text-green-400' : 'bg-surface-2 text-ink-2 hover:bg-surface-3'
                    }`}
                  >
                    {referralCopied ? 'Copiado!' : 'Copiar'}
                  </button>
                </div>
                <p className="text-ink-4 text-xs mt-1">
                  Código: <span className="text-ink-2 font-mono font-bold">{referral.referral_code}</span>
                </p>
              </div>

              <div className="font-mono grid grid-cols-3 gap-3">
                <div className="bg-surface-1 rounded-lg p-3 text-center">
                  <p className="text-xl font-black text-ink-1">{referral.total_indicated}</p>
                  <p className="text-ink-3 text-xs mt-0.5">Indicados</p>
                </div>
                <div className="bg-surface-1 rounded-lg p-3 text-center">
                  <p className="text-xl font-black text-green-400">{referral.total_converted}</p>
                  <p className="text-ink-3 text-xs mt-0.5">Convertidos</p>
                </div>
                <div className="bg-surface-1 rounded-lg p-3 text-center">
                  <p className="text-xl font-black text-yellow-400">{referral.days_earned}</p>
                  <p className="text-ink-3 text-xs mt-0.5">Dias ganhos</p>
                </div>
              </div>

              {referral.total_indicated === 0 && (
                <p className="text-ink-4 text-xs text-center">
                  Compartilhe seu link: cada amigo que assinar VIP te dá +1 dia grátis!
                </p>
              )}
            </>
          ) : referralLoaded ? (
            <p className="text-ink-4 text-xs">Não foi possível carregar os dados de indicação. Tente recarregar a página.</p>
          ) : (
            <div className="flex items-center gap-2 text-ink-4 text-xs">
              <div className="w-4 h-4 border border-line-strong border-t-transparent rounded-full animate-spin" />
              Carregando dados de indicação...
            </div>
          )}
        </div>

        {/* Alertas e conquistas. Vêm de /api/personal, tela própria dentro do
            perfil pra não criar mais uma rota pra dois blocos curtos. */}
        <AlertsAndAchievements />
    </PageShell>
  )
}
