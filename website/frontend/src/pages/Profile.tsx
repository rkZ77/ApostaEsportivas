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

export default function Profile() {
  const { user, updateUser } = useAuth()
  const navigate = useNavigate()

  const [name, setName]             = useState(user?.name ?? '')
  const [phone, setPhone]           = useState(user?.phone ?? '')
  const [cpf, setCpf]               = useState('')
  const [currentPwd, setCurrentPwd] = useState('')
  const [newPwd, setNewPwd]         = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')
  const [loading, setLoading]       = useState(false)
  const [successMsg, setSuccessMsg] = useState('')
  const [error, setError]           = useState('')
  const [meData, setMeData]         = useState<any>(null)

  const [avatarUploading, setAvatarUploading] = useState(false)
  const [avatarPreview, setAvatarPreview]     = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [referral, setReferral] = useState<ReferralData | null>(null)
  const [referralCopied, setReferralCopied] = useState(false)

  useEffect(() => {
    api.get('/auth/referral').then(r => setReferral(r.data)).catch(() => {})
    api.get('/auth/me').then(r => setMeData(r.data)).catch(() => {})
  }, [])

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

    if (newPwd && newPwd !== confirmPwd) {
      setError('As novas senhas não coincidem'); return
    }
    if (newPwd) {
      if (newPwd.length < 8) { setError('Senha deve ter pelo menos 8 caracteres'); return }
    }

    const body: Record<string, string> = {}
    if (name !== user?.name)               body.name = name
    if (phone !== (user?.phone ?? ''))     body.phone = phone
    if (cpf.trim())                        body.cpf = cpf.trim()
    if (newPwd) { body.current_password = currentPwd; body.new_password = newPwd }

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
      setCurrentPwd(''); setNewPwd(''); setConfirmPwd('')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao atualizar')
    } finally {
      setLoading(false)
    }
  }

  const planBadge: Record<string, string> = {
    free: 'badge-free', vip: 'badge-vip', admin: 'badge-admin',
  }

  const currentAvatar = avatarPreview ?? user?.avatar_url ?? null

  return (
    <div className="min-h-screen bg-black">
      <Navbar />
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-2xl mx-auto px-4 py-4 flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="text-zinc-500 hover:text-white transition-colors text-lg leading-none">←</button>
          <div>
            <h1 className="text-base font-black text-white">Meu Perfil</h1>
            <p className="text-zinc-500 text-xs mt-0.5">Altere nome, foto e senha da sua conta</p>
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
            <p className="text-zinc-500 text-xs truncate">{user?.email}</p>
            <p className="text-zinc-600 text-xs mt-1">Clique na foto para alterar</p>
          </div>
          <span className={planBadge[user?.plan ?? 'free']}>
            {user?.plan === 'vip' ? 'VIP' : user?.plan === 'admin' ? 'ADMIN' : 'FREE'}
          </span>
        </div>

        {/* Formulário */}
        <form onSubmit={handleSubmit} className="card p-6 space-y-5">
          <div>
            <label className="text-xs text-zinc-500 block mb-1.5">Nome</label>
            <input className="input w-full" value={name} onChange={e => setName(e.target.value)} required />
          </div>

          <div>
            <label className="text-xs text-zinc-500 block mb-1.5">WhatsApp / Telefone <span className="text-zinc-600">(opcional)</span></label>
            <input className="input w-full" value={phone} onChange={e => setPhone(e.target.value)} placeholder="(11) 99999-9999" type="tel" />
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
                  Adicione seu CPF e salve — você receberá 2 dias de VIP grátis.
                </p>
              )}
            </div>
          )}

          <hr className="border-zinc-800" />
          <p className="text-xs text-zinc-500 font-semibold uppercase tracking-wider">Trocar senha</p>

          <div>
            <label className="text-xs text-zinc-500 block mb-1.5">Senha atual</label>
            <input type="password" className="input w-full" placeholder="Deixe em branco para não alterar"
              value={currentPwd} onChange={e => setCurrentPwd(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-zinc-500 block mb-1.5">Nova senha</label>
              <input type="password" className="input w-full" placeholder="Mínimo 8 caracteres"
                value={newPwd} onChange={e => setNewPwd(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-zinc-500 block mb-1.5">Confirmar</label>
              <input type="password" className="input w-full" placeholder="Repita a nova senha"
                value={confirmPwd} onChange={e => setConfirmPwd(e.target.value)} />
            </div>
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
                  Compartilhe seu link — cada amigo que assinar VIP te dá +1 dia grátis!
                </p>
              )}
            </>
          ) : (
            <div className="flex items-center gap-2 text-zinc-600 text-xs">
              <div className="w-4 h-4 border border-zinc-700 border-t-transparent rounded-full animate-spin" />
              Carregando dados de indicação...
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
