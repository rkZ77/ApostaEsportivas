import { useEffect, useState } from 'react'
import {
  AlertTriangle, CheckCircle2, Copy, Eye, Mail, MessageCircle, Send,
} from 'lucide-react'
import api from '../services/api'

/*
 * Disparos: a aba pra FALAR com quem sumiu.
 *
 * O /admin já media o buraco do meio do funil (aba Funil, painel de
 * engajamento antes dela), e medir é o que sobra quando não dá pra agir: não
 * existia nenhuma forma de alcançar quem cadastrou e nunca voltou.
 *
 * A tela mostra o público ANTES do botão, de propósito. Mesmo motivo do painel
 * de planos vencidos: disparo manda e-mail de verdade, e um clique no escuro
 * não pode ser a forma de descobrir pra quantas pessoas ele foi.
 *
 * Os dois canais não funcionam igual, e a tela não finge que sim:
 *
 *   E-MAIL sai daqui, em lote, com teto por clique.
 *   WHATSAPP sai na mão, uma conversa por vez, pelo link wa.me. A política da
 *   Meta pra vertical de aposta trata denúncia no nível da conta, e o número é
 *   um só · campanha em lote pra quem não pediu é o jeito mais rápido de
 *   perdê-lo. O aviso automático que existe (pick ao vivo) é outro caso: ali a
 *   pessoa ligou o opt-in no próprio perfil.
 */

interface CampanhaResumo {
  id: string
  nome: string
  objetivo: string
  assunto: string
  cta: string
  publico_email: number
  publico_whatsapp: number
  ja_enviados: Record<string, { n: number; ultimo: string }>
}

interface Dados {
  campanhas: CampanhaResumo[]
  base: { total: number; opt_out: number; wa_opt_in: number; tel_verificado: number }
  envio_email_ativo: boolean
  whatsapp_automatico: boolean
  limite_max: number
}

interface Previa {
  assunto: string
  html: string
  fila: { nome: string; email: string; plano: string; ultimo_login: string | null }[]
}

interface ContatoWA {
  user_id: number
  nome: string
  telefone: string
  plano: string
  ultimo_login: string | null
  texto: string
  link: string
}

const diasDesde = (iso: string | null) =>
  iso === null ? null : Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)

export default function AdminDisparos() {
  const [d, setD] = useState<Dados | null>(null)
  const [erro, setErro] = useState('')
  const [aberta, setAberta] = useState<string | null>(null)
  const [canal, setCanal] = useState<'email' | 'whatsapp'>('email')
  const [previa, setPrevia] = useState<Previa | null>(null)
  const [contatos, setContatos] = useState<ContatoWA[]>([])
  const [carregandoPainel, setCarregandoPainel] = useState(false)
  const [limite, setLimite] = useState(50)
  const [enviando, setEnviando] = useState(false)
  const [resultado, setResultado] = useState('')

  const carregar = () =>
    api.get('/admin/disparos')
      .then(r => setD(r.data))
      .catch(() => setErro('Não foi possível carregar as campanhas.'))

  useEffect(() => { carregar() }, [])

  // Uma campanha aberta por vez: a prévia é um e-mail inteiro renderizado, e
  // três abertas ao mesmo tempo viram três iframes concorrendo na tela.
  const abrir = async (id: string, novoCanal: 'email' | 'whatsapp') => {
    if (aberta === id && canal === novoCanal) { setAberta(null); return }
    setAberta(id)
    setCanal(novoCanal)
    setPrevia(null)
    setContatos([])
    setResultado('')
    setCarregandoPainel(true)
    try {
      if (novoCanal === 'email') {
        const { data } = await api.get(`/admin/disparos/${id}/previa`)
        setPrevia(data)
      } else {
        const { data } = await api.get(`/admin/disparos/${id}/whatsapp`)
        setContatos(data.fila)
      }
    } catch {
      setErro('Não foi possível montar a prévia desta campanha.')
    } finally {
      setCarregandoPainel(false)
    }
  }

  const disparar = async (id: string, teste: boolean) => {
    setEnviando(true)
    setErro('')
    try {
      const { data } = await api.post(`/admin/disparos/${id}/enviar`, { limite, teste })
      setResultado(
        teste
          ? `Teste enviado para ${data.para}.`
          : `${data.enviados} enviado(s), ${data.falhas} falha(s). Ainda faltam ${data.restam}.`,
      )
      if (!teste) await carregar()
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErro(msg || 'O disparo não foi concluído. Tente de novo.')
    } finally {
      setEnviando(false)
    }
  }

  const marcarEnviado = async (id: string, userId: number) => {
    try {
      await api.post(`/admin/disparos/${id}/marcar`, { user_ids: [userId], canal: 'whatsapp' })
      setContatos(c => c.filter(x => x.user_id !== userId))
      await carregar()
    } catch {
      setErro('Não foi possível registrar esse envio.')
    }
  }

  if (!d) return erro ? <p className="text-xs text-red-400">{erro}</p> : null

  return (
    <div className="space-y-4">
      {/* Quanto da base cada número representa. Sem isso, "412 elegíveis" pode
          ser metade da base ou pode ser 3%. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { l: 'Contas ativas', v: d.base.total, sub: 'sem admin e sem excluída' },
          { l: 'Saíram do e-mail', v: d.base.opt_out, sub: 'pediram pra não receber',
            c: d.base.opt_out > 0 ? 'text-amber-400' : 'text-ink-1' },
          { l: 'Telefone confirmado', v: d.base.tel_verificado, sub: 'passaram pelo SMS' },
          { l: 'Opt-in de WhatsApp', v: d.base.wa_opt_in, sub: 'ligaram os avisos',
            c: d.base.wa_opt_in > 0 ? 'text-green-400' : 'text-ink-3' },
        ].map(x => (
          <div key={x.l} className="bg-surface-1 border border-line rounded-lg px-4 py-3">
            <div className={`font-mono text-2xl font-black ${x.c ?? 'text-ink-1'}`}>{x.v}</div>
            <div className="text-xs text-ink-3 mt-0.5">{x.l}</div>
            <div className="text-[10px] text-ink-4 mt-0.5">{x.sub}</div>
          </div>
        ))}
      </div>

      {!d.envio_email_ativo && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/[0.07] px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-[11px] text-ink-2 leading-relaxed">
            Envio em lote desligado neste ambiente. O staging aponta pro banco de
            produção: disparar daqui gravaria o registro de envio da base real, e o
            disparo de verdade deixaria essa gente de fora depois. O botão de teste
            continua valendo, ele manda só pro seu e-mail.
          </p>
        </div>
      )}

      {d.campanhas.map(c => {
        const enviadoEmail = c.ja_enviados.email?.n ?? 0
        const enviadoWa = c.ja_enviados.whatsapp?.n ?? 0
        const estaAberta = aberta === c.id
        return (
          <div key={c.id} className="bg-surface-1 border border-line rounded-lg p-4">
            {/* Empilha no celular: com os dois botões na mesma linha em 390px,
                o texto do objetivo sobra uns 60px e desce uma palavra por
                linha. O `flex-1` não resolve porque quem manda na largura ali
                é o conteúdo dos botões. */}
            <div className="flex flex-col sm:flex-row items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-bold text-ink-1">{c.nome}</h3>
                <p className="text-[11px] text-ink-4 mt-1 leading-relaxed max-w-2xl">
                  {c.objetivo}
                </p>
              </div>
              <div className="flex gap-2 shrink-0 w-full sm:w-auto">
                <button
                  onClick={() => abrir(c.id, 'email')}
                  className={`flex-1 sm:flex-none justify-center px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors flex items-center gap-1.5 ${
                    estaAberta && canal === 'email'
                      ? 'bg-green-500 border-green-500 text-black'
                      : 'border-line-strong text-ink-2 hover:text-ink-1 hover:border-ink-4'
                  }`}
                >
                  <Mail className="w-3.5 h-3.5" />
                  {c.publico_email} por e-mail
                </button>
                <button
                  onClick={() => abrir(c.id, 'whatsapp')}
                  className={`flex-1 sm:flex-none justify-center px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors flex items-center gap-1.5 ${
                    estaAberta && canal === 'whatsapp'
                      ? 'bg-green-500 border-green-500 text-black'
                      : 'border-line-strong text-ink-2 hover:text-ink-1 hover:border-ink-4'
                  }`}
                >
                  <MessageCircle className="w-3.5 h-3.5" />
                  {c.publico_whatsapp} no WhatsApp
                </button>
              </div>
            </div>

            {(enviadoEmail > 0 || enviadoWa > 0) && (
              <p className="text-[10px] text-ink-4 mt-2 flex items-center gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-green-400" />
                Já recebeu: {enviadoEmail} por e-mail, {enviadoWa} no WhatsApp.
                Quem recebeu não volta pra fila.
              </p>
            )}

            {estaAberta && (
              <div className="mt-4 border-t border-line pt-4">
                {carregandoPainel && <p className="text-xs text-ink-4">Montando...</p>}

                {canal === 'email' && previa && (
                  <>
                    <div className="flex items-center gap-2 mb-2">
                      <Eye className="w-3.5 h-3.5 text-ink-3" />
                      <span className="text-xs text-ink-2 font-semibold">{previa.assunto}</span>
                    </div>
                    {/* srcDoc e sandbox vazio: o HTML de e-mail traz estilo
                        inline e <table> com largura fixa, e solto na página ele
                        atropela o layout do admin. */}
                    <iframe
                      title="Prévia do e-mail"
                      srcDoc={previa.html}
                      sandbox=""
                      className="w-full h-[420px] rounded-lg border border-line bg-white"
                    />

                    {previa.fila.length > 0 && (
                      <div className="mt-3">
                        <p className="text-[11px] text-ink-3 mb-1.5">Primeiros da fila:</p>
                        <div className="space-y-1">
                          {previa.fila.map((f, i) => (
                            <div key={i} className="bg-surface-2 rounded-md px-3 py-1.5 flex items-center justify-between gap-3">
                              <span className="text-xs text-ink-2 truncate">{f.nome}</span>
                              <span className="text-[10px] text-ink-4 shrink-0">
                                {f.email} · {diasDesde(f.ultimo_login) === null
                                  ? 'nunca entrou'
                                  : `há ${diasDesde(f.ultimo_login)}d`}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="mt-4 flex items-end gap-2 flex-wrap">
                      <label className="text-[11px] text-ink-3">
                        Quantos neste lote
                        <input
                          type="number"
                          min={1}
                          max={d.limite_max}
                          value={limite}
                          onChange={e => setLimite(Number(e.target.value))}
                          className="input mt-1 w-24 text-sm block"
                        />
                      </label>
                      <button
                        onClick={() => disparar(c.id, true)}
                        disabled={enviando}
                        className="px-3 py-2 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:text-ink-1 hover:border-ink-4 disabled:opacity-30 transition-colors"
                      >
                        Mandar teste pra mim
                      </button>
                      <button
                        onClick={() => disparar(c.id, false)}
                        disabled={enviando || !d.envio_email_ativo || c.publico_email === 0}
                        className="px-4 py-2 rounded-lg text-xs font-bold bg-green-500 text-black hover:bg-green-400 disabled:opacity-30 transition-colors flex items-center gap-1.5"
                      >
                        <Send className="w-3.5 h-3.5" />
                        {enviando ? 'Enviando...' : `Disparar ${Math.min(limite, c.publico_email)}`}
                      </button>
                    </div>
                    <p className="text-[10px] text-ink-4 mt-2 leading-relaxed">
                      O disparo sai em lotes porque taxa de rejeição só aparece depois
                      do envio: um assunto ruim descoberto com a base inteira já
                      queimada não tem volta. Todo e-mail leva link de descadastro,
                      e quem clicar sai só do marketing, a conta continua ativa.
                    </p>
                  </>
                )}

                {canal === 'whatsapp' && !carregandoPainel && (
                  <>
                    <p className="text-[11px] text-ink-4 mb-3 leading-relaxed">
                      Aqui não tem botão de disparar, e a ausência é a decisão. A
                      política da Meta pra vertical de aposta trata denúncia no nível
                      da conta, e o número é um só: mandar em lote pra quem não pediu
                      é o caminho mais curto pra perdê-lo. Abra a conversa, mande, e
                      marque depois, pra a pessoa sair da fila.
                    </p>
                    {contatos.length === 0 ? (
                      <p className="text-xs text-ink-4">
                        Ninguém na fila. Só entra quem tem telefone confirmado por SMS.
                      </p>
                    ) : (
                      <div className="space-y-1.5">
                        {contatos.map(ct => (
                          <div key={ct.user_id} className="bg-surface-2 rounded-md px-3 py-2 flex items-center justify-between gap-3 flex-wrap">
                            <div className="min-w-0">
                              <div className="text-ink-1 text-sm font-semibold truncate">{ct.nome}</div>
                              <div className="text-[10px] text-ink-4">
                                {ct.telefone} · {diasDesde(ct.ultimo_login) === null
                                  ? 'nunca entrou'
                                  : `há ${diasDesde(ct.ultimo_login)}d`}
                              </div>
                            </div>
                            <div className="flex gap-1.5 shrink-0">
                              <button
                                onClick={() => navigator.clipboard.writeText(ct.texto)}
                                title="Copiar o texto"
                                className="p-2 rounded-lg border border-line-strong text-ink-3 hover:text-ink-1 transition-colors"
                              >
                                <Copy className="w-3.5 h-3.5" />
                              </button>
                              <a
                                href={ct.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:text-ink-1 hover:border-ink-4 transition-colors flex items-center gap-1.5"
                              >
                                <MessageCircle className="w-3.5 h-3.5" /> Abrir
                              </a>
                              <button
                                onClick={() => marcarEnviado(c.id, ct.user_id)}
                                className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-green-500 text-black hover:bg-green-400 transition-colors"
                              >
                                Mandei
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}

                {resultado && <p className="text-[11px] text-green-400 mt-3">{resultado}</p>}
                {erro && <p className="text-[11px] text-red-400 mt-3">{erro}</p>}
              </div>
            )}
          </div>
        )
      })}

      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <h3 className="text-xs font-semibold text-ink-3 flex items-center gap-1.5 mb-2">
          <MessageCircle className="w-3.5 h-3.5" /> Aviso automático de pick ao vivo
        </h3>
        <p className="text-[11px] text-ink-4 leading-relaxed">
          {d.whatsapp_automatico
            ? `Ligado. Quando o motor ao vivo publica, o aviso sai no WhatsApp de quem tem o Pick IA Pro e ligou o opt-in no perfil, com teto por dia e uma mensagem por pick. É o único produto que vale mensagem: a odd do ao vivo vence em minutos, e quem não está com a aba aberta perde.`
            : `Desligado neste ambiente: falta WHATSAPP_PROVIDER=cloud com token e phone id. Os avisos ficam no log em vez de sair, que é o que deixa o fluxo ser testado sem gastar aprovação de template.`}
        </p>
        <p className="text-[11px] text-ink-4 leading-relaxed mt-2">
          {d.base.wa_opt_in === 0
            ? 'Ninguém ligou o opt-in ainda. O interruptor fica no perfil, e só aparece pra quem confirmou o telefone por SMS.'
            : `${d.base.wa_opt_in} pessoa(s) autorizaram receber.`}
        </p>
      </div>
    </div>
  )
}
