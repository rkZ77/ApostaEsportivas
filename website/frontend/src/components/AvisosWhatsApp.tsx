import { useEffect, useState } from 'react'
import { MessageCircle, Radio } from 'lucide-react'
import api from '../services/api'

/*
 * O interruptor que faltava.
 *
 * A coluna `whatsapp_opt_in` existe no banco desde 08/2026 e nunca teve tela:
 * era um campo que ninguém podia ligar, e por isso a audiência de WhatsApp no
 * /admin era zero permanente, com um aviso explicando por que era zero.
 *
 * Aqui a pessoa autoriza, escolhe o que quer receber e desliga na mesma tela.
 * Duas regras moram neste componente:
 *
 *   TELEFONE VERIFICADO É PRÉ-REQUISITO. Sem SMS confirmado o card mostra o
 *   motivo em vez do toggle: número não verificado pode ser o do vizinho, e
 *   mandar aviso pro número errado é denúncia, que custa o número inteiro da
 *   operação, não uma mensagem.
 *
 *   O CARD SOME quando o ambiente não tem provedor. Um toggle que aceita o
 *   clique e não entrega aviso nenhum é pior do que não existir, e é o mesmo
 *   raciocínio do card de Telefone com `sms_disponivel`.
 */

interface Prefs {
  disponivel: boolean
  telefone: string
  phone_verified: boolean
  opt_in: boolean
  ao_vivo: boolean
  picks_do_dia: boolean
  resultado: boolean
  ao_vivo_no_plano: boolean
  teto_dia: number
}

function Toggle({ ligado, onChange, titulo, texto, Icon, desabilitado }: {
  ligado: boolean
  onChange: (v: boolean) => void
  titulo: string
  texto: string
  Icon: typeof Radio
  desabilitado?: boolean
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!ligado)}
      disabled={desabilitado}
      className={`w-full text-left flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors disabled:opacity-40 ${
        ligado ? 'border-green-500/40 bg-green-500/[0.06]' : 'border-line hover:border-ink-4'
      }`}
    >
      <Icon className={`w-4 h-4 shrink-0 mt-0.5 ${ligado ? 'text-green-400' : 'text-ink-4'}`} />
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-semibold text-ink-1">{titulo}</span>
        <span className="block text-[11px] text-ink-4 leading-relaxed mt-0.5">{texto}</span>
      </span>
      <span className={`shrink-0 w-9 h-5 rounded-full relative transition-colors ${
        ligado ? 'bg-green-500' : 'bg-surface-2 border border-line-strong'
      }`}>
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${
          ligado ? 'left-[18px]' : 'left-0.5'
        }`} />
      </span>
    </button>
  )
}

export default function AvisosWhatsApp() {
  const [p, setP] = useState<Prefs | null>(null)
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')
  const [ok, setOk] = useState('')

  useEffect(() => {
    api.get('/notifications/whatsapp')
      .then(r => setP(r.data))
      .catch(() => setP(null))
  }, [])

  if (!p || !p.disponivel) return null

  const salvar = async (novo: Prefs) => {
    setP(novo)
    setSalvando(true)
    setErro('')
    setOk('')
    try {
      await api.put('/notifications/whatsapp', {
        opt_in: novo.opt_in,
        ao_vivo: novo.ao_vivo,
        picks_do_dia: novo.picks_do_dia,
        resultado: novo.resultado,
      })
      setOk('Preferências salvas.')
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErro(msg || 'Não foi possível salvar agora. Tente de novo.')
      // Volta o que a tela mostrava: toggle que fica ligado sem ter salvo faz
      // a pessoa acreditar que vai receber aviso que nunca vem.
      api.get('/notifications/whatsapp').then(r => setP(r.data)).catch(() => {})
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="card p-6 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold text-ink-1">Avisos no WhatsApp</h2>
          <p className="text-ink-3 text-xs mt-0.5">
            {p.opt_in ? `Enviando para ${p.telefone}` : 'Desligado'}
          </p>
        </div>
      </div>

      {!p.phone_verified ? (
        <p className="text-xs text-ink-4 leading-relaxed">
          Confirme seu telefone por SMS no card acima para liberar os avisos. A
          confirmação existe para garantir que a mensagem vai para o seu número,
          e não para um digitado errado.
        </p>
      ) : (
        <>
          <Toggle
            ligado={p.opt_in}
            onChange={v => salvar({ ...p, opt_in: v })}
            titulo="Quero receber avisos no WhatsApp"
            texto="Só aviso, nunca conteúdo. Você desliga aqui quando quiser."
            Icon={MessageCircle}
            desabilitado={salvando}
          />

          {p.opt_in && (
            <div className="space-y-2 pl-1">
              <Toggle
                ligado={p.ao_vivo && p.ao_vivo_no_plano}
                onChange={v => salvar({ ...p, ao_vivo: v })}
                titulo="Oportunidade ao vivo"
                texto={p.ao_vivo_no_plano
                  ? `Chega na hora em que o motor publica, com jogo, mercado e odd. No máximo ${p.teto_dia} por dia.`
                  : 'Disponível no Pick IA Pro, que é o plano que abre o produto ao vivo.'}
                Icon={Radio}
                desabilitado={salvando || !p.ao_vivo_no_plano}
              />
              <Toggle
                ligado={p.picks_do_dia}
                onChange={v => salvar({ ...p, picks_do_dia: v })}
                titulo="Picks do dia publicados"
                texto="Uma mensagem por dia, quando a leva do dia entra no site."
                Icon={MessageCircle}
                desabilitado={salvando}
              />
              <Toggle
                ligado={p.resultado}
                onChange={v => salvar({ ...p, resultado: v })}
                titulo="Resultado das suas entradas"
                texto="Só dos picks que você seguiu. Anulada não vira mensagem, porque não muda nada na sua banca."
                Icon={MessageCircle}
                desabilitado={salvando}
              />
            </div>
          )}

          <p className="text-[11px] text-ink-4 leading-relaxed">
            A regra é a mesma do sino: se a mensagem não muda uma decisão sua,
            ela não é enviada. Nada de promoção e nada de bom dia.
          </p>
        </>
      )}

      {ok && <p className="text-green-400 text-xs">{ok}</p>}
      {erro && <p className="text-red-400 text-xs">{erro}</p>}
    </div>
  )
}
