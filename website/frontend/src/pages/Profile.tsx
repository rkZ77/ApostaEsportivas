import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'
import Avatar from '../components/Avatar'

interface ReferralData {
  referral_code: string
  referral_link: string
  total_indicated: number
  total_converted: number
  days_earned: number
}

function maskPhone(value: string): string {
  const d = value.replace(/\D/g, '').slice(0, 11)
  if (d.length <= 2)  return d.length ? `(${d}` : ''
  if (d.length <= 6)  return `(${d.slice(0,2)}) ${d.slice(2)}`
  if (d.length <= 10) return `(${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`
  return `(${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7)}`
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

  const [referral, setReferral]       = useState<ReferralData | null>(null)
  const [referralLoaded, setReferralLoaded] = useState(false)
  const [referralCopied, setReferralCopied] = useState(false)

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
    free:  { label: 'FREE',  color: 'text-zinc-400' },
    trial: { label: 'TRIAL', color: 'text-amber-400' },
    vip:   { label: 'VIP',   color: 'text-yellow-400' },
    admin: { label: 'ADMIN', color: 'text-purple-400' },
  }
  const pm = planMeta[user?.plan ?? 'free'] ?? planMeta.free

  const currentAvatar = avatarPreview ?? user?.avatar_url ?? null

  return (
    <div className="min-h-screen bg-black relative">
      <Navbar />
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-2xl mx-auto px-4 py-4 flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="flex items-center justify-center w-8 h-8 rounded-full border border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-white transition-colors shrink-0"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg></button>
          <div>
            <h1 className="text-base font-black text-white">Meu Perfil</h1>
            <p className="text-zinc-500 text-xs mt-0.5">Gerencie suas informações e preferências</p>
          </div>
        </div>
      </div>

      <main className="max-w-2xl mx-auto px-4 py-8 space-y-6">
        {/* Info atual + upload de avatar */}
        <div className="card p-5 flex items-center gap-4">
          <div className="relative group cursor-pointer shrink-0" onClick={handleAvatarClick}>
            {user?.name && (
              <Avatar name={user.name} imageUrl={currentAvatar} size="lg" />
            )}
            <div className="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
              {avatarUploading
                ? <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                : <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
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
            <p className="text-white font-bold truncate">{user?.name}</p>
            {meData?.username && <p className="text-green-500 text-xs font-semibold">@{meData.username}</p>}
            <p className="text-zinc-500 text-xs truncate mt-0.5">{user?.email}</p>
            <p className="text-zinc-600 text-xs mt-1.5 flex items-center gap-1">
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
          <p className="text-xs text-zinc-500 font-semibold uppercase tracking-wider mb-4">Assinatura</p>
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="text-zinc-400 text-sm">Status atual:</span>
                <span className={`text-sm font-black ${pm.color}`}>{pm.label}</span>
              </div>
              {countdown && (
                <p className="text-zinc-400 text-sm">
                  Expira em <span className="font-bold text-white tabular-nums">{countdown}</span>
                </p>
              )}
              {user?.plan === 'free' && (
                <p className="text-zinc-500 text-xs">Faça upgrade para acessar picks VIP</p>
              )}
            </div>
            {(user?.plan === 'free' || user?.plan === 'trial') && (
              <button
                type="button"
                onClick={() => navigate('/planos')}
                className="shrink-0 bg-green-600 hover:bg-green-500 text-white font-bold text-sm px-5 py-2.5 rounded-xl transition-colors"
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
          <p className="text-xs text-zinc-500 font-semibold uppercase tracking-wider">Informações pessoais</p>
          <div>
            <label className="text-xs text-zinc-500 block mb-1.5">Nome completo</label>
            <input className="input w-full" value={name} onChange={e => setName(e.target.value)} required />
          </div>

          <div>
            <label className="text-xs text-zinc-500 block mb-1.5">Nome de usuário <span className="text-zinc-600 font-normal">(para login)</span></label>
            <input className="input w-full" value={username}
              onChange={e => setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
              placeholder="seu_usuario" maxLength={20} />
            <p className="text-xs text-zinc-600 mt-1">3–20 caracteres · letras minúsculas, números e _</p>
          </div>

          <div>
            <label className="text-xs text-zinc-500 block mb-1.5">WhatsApp <span className="text-zinc-600 font-normal">(opcional)</span></label>
            <input className="input w-full" value={phone} onChange={e => setPhone(maskPhone(e.target.value))} placeholder="(11) 99999-9999" type="tel" inputMode="numeric" />
          </div>

          {!meData?.has_cpf && (
            <div>
              <label className="text-xs text-zinc-500 block mb-1.5">
                CPF <span className="text-zinc-600">(necessário para ativar o teste gratuito)</span>
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

          <hr className="border-zinc-800" />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-zinc-500 font-semibold uppercase tracking-wider">Senha</p>
              <p className="text-xs text-zinc-600 mt-0.5">Para alterar, use o link enviado por email</p>
            </div>
            <button
              type="button"
              onClick={() => navigate('/forgot-password')}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors font-semibold border border-blue-400/20 hover:border-blue-400/40 bg-blue-400/5 px-3 py-2 rounded-lg"
            >
              Alterar senha
            </button>
          </div>

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

        {/* E-mail e verificação */}
        <div className="card p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-black text-white">E-mail</h2>
              <p className="text-zinc-500 text-xs mt-0.5">Verificação e alteração</p>
            </div>
            {user?.email_verified
              ? <span className="text-xs font-bold text-green-400 bg-green-400/10 border border-green-400/20 px-2.5 py-1 rounded-lg">Verificado ✓</span>
              : <span className="text-xs font-bold text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-2.5 py-1 rounded-lg">Não verificado</span>
            }
          </div>

          <p className="text-sm text-zinc-300 font-medium">{emailChanged || user?.email}</p>

          {!user?.email_verified && (
            <div className="space-y-3">
              {emailResent && (
                <p className="text-green-400 text-xs font-semibold">E-mail enviado! Verifique também a pasta de spam.</p>
              )}
              <div className="flex gap-2">
                <button
                  onClick={handleResendEmail}
                  disabled={emailResending || emailCooldown > 0}
                  className="flex-1 py-2.5 rounded-xl border border-zinc-700 hover:border-zinc-500 text-zinc-300 hover:text-white text-xs font-semibold transition-colors disabled:opacity-50"
                >
                  {emailResending ? 'Enviando…' : emailCooldown > 0 ? `Reenviar em ${emailCooldown}s` : 'Reenviar confirmação'}
                </button>
                {!showEmailChange && (
                  <button
                    onClick={() => setShowEmailChange(true)}
                    className="flex-1 py-2.5 rounded-xl border border-blue-500/30 hover:border-blue-400/50 text-blue-400 hover:text-blue-300 text-xs font-semibold transition-colors"
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
                      className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-bold text-sm transition-colors">
                      {emailChanging ? 'Salvando…' : 'Salvar e reenviar'}
                    </button>
                    <button type="button" onClick={() => { setShowEmailChange(false); setEmailChangeErr(''); setEmailPassword('') }}
                      className="px-4 py-2.5 rounded-xl border border-zinc-700 text-zinc-400 text-sm hover:border-zinc-500 transition-colors">
                      Cancelar
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}
        </div>

        {/* Seção de Indicações */}
        <div className="card p-6 space-y-4">
          <div>
            <h2 className="text-sm font-black text-white">Programa de Indicações</h2>
            <p className="text-zinc-500 text-xs mt-0.5">Indique amigos e ganhe 1 dia VIP por cada conversão</p>
          </div>

          {referral ? (
            <>
              <div>
                <p className="text-xs text-zinc-500 mb-1.5">Seu link de indicação</p>
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-xs text-zinc-300 font-mono truncate select-all">
                    {referral.referral_link}
                  </div>
                  <button
                    onClick={copyReferralLink}
                    className={`shrink-0 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                      referralCopied ? 'bg-green-500/20 text-green-400' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                    }`}
                  >
                    {referralCopied ? 'Copiado!' : 'Copiar'}
                  </button>
                </div>
                <p className="text-zinc-600 text-xs mt-1">
                  Código: <span className="text-zinc-400 font-mono font-bold">{referral.referral_code}</span>
                </p>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="bg-zinc-900 rounded-lg p-3 text-center">
                  <p className="text-xl font-black text-white">{referral.total_indicated}</p>
                  <p className="text-zinc-500 text-xs mt-0.5">Indicados</p>
                </div>
                <div className="bg-zinc-900 rounded-lg p-3 text-center">
                  <p className="text-xl font-black text-green-400">{referral.total_converted}</p>
                  <p className="text-zinc-500 text-xs mt-0.5">Convertidos</p>
                </div>
                <div className="bg-zinc-900 rounded-lg p-3 text-center">
                  <p className="text-xl font-black text-yellow-400">{referral.days_earned}</p>
                  <p className="text-zinc-500 text-xs mt-0.5">Dias ganhos</p>
                </div>
              </div>

              {referral.total_indicated === 0 && (
                <p className="text-zinc-600 text-xs text-center">
                  Compartilhe seu link: cada amigo que assinar VIP te dá +1 dia grátis!
                </p>
              )}
            </>
          ) : referralLoaded ? (
            <p className="text-zinc-600 text-xs">Não foi possível carregar os dados de indicação. Tente recarregar a página.</p>
          ) : (
            <div className="flex items-center gap-2 text-zinc-600 text-xs">
              <div className="w-4 h-4 border border-zinc-700 border-t-transparent rounded-full animate-spin" />
              Carregando dados de indicação...
            </div>
          )}
        </div>
      </main>

      {/* Copa do Mundo 2026 — canto inferior direito */}
      <div className="fixed bottom-6 right-6 flex flex-col items-center gap-1 opacity-70 hover:opacity-100 transition-opacity pointer-events-none select-none">
        <img src="/logo-copa-mundo.png" alt="Copa do Mundo 2026" className="w-14 h-14 object-contain drop-shadow-lg" />
        <span className="text-zinc-500 text-[10px] font-semibold tracking-wide">Copa 2026</span>
      </div>
    </div>
  )
}
