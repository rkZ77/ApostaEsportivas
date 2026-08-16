import { useEffect, useState } from 'react'
import { AlertTriangle, MessageCircle } from 'lucide-react'
import api from '../services/api'

/*
 * Quem ainda aparece, quem sumiu, e quem o WhatsApp alcançaria.
 *
 * As duas leituras ficam juntas porque são a mesma pergunta vista de dois
 * ângulos: a audiência de cada aviso é um recorte de atividade. Separar em duas
 * telas obrigaria a comparar números de lugares diferentes justamente na hora
 * de decidir um disparo.
 *
 * O painel mostra AUDIÊNCIA, não fila de envio. Nada de WhatsApp está
 * implementado do lado do disparo, e o aviso no rodapé existe pra que o número
 * não seja lido como "vai sair hoje".
 */

interface Dados {
  usuarios: {
    total: number; hoje: number; semana: number; mes: number
    nunca_entrou: number; inativos_10d: number
    com_telefone: number; com_opt_in: number; vips: number
  }
  whatsapp: {
    picks_do_dia: number; resultado: number; reengajamento: number
    envio_ativo: boolean
  }
}

export default function AdminEngajamento() {
  const [d, setD] = useState<Dados | null>(null)

  useEffect(() => {
    api.get('/admin/users/engajamento').then(r => setD(r.data)).catch(() => setD(null))
  }, [])

  if (!d) return null

  const pct = (n: number) => d.usuarios.total ? Math.round(n / d.usuarios.total * 100) : 0

  return (
    <div className="space-y-4 mb-6">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {[
          { l: 'Usuários',      v: d.usuarios.total },
          { l: 'Ativos hoje',   v: d.usuarios.hoje,    sub: `${pct(d.usuarios.hoje)}% da base` },
          { l: 'Ativos 7 dias', v: d.usuarios.semana,  sub: `${pct(d.usuarios.semana)}% da base` },
          { l: 'Sumidos',       v: d.usuarios.inativos_10d, sub: 'sem entrar há 10 dias',
            c: d.usuarios.inativos_10d > 0 ? 'text-amber-400' : 'text-ink-1' },
          { l: 'Nunca entraram', v: d.usuarios.nunca_entrou, sub: 'cadastraram e sumiram',
            c: d.usuarios.nunca_entrou > 0 ? 'text-red-400' : 'text-ink-1' },
        ].map(x => (
          <div key={x.l} className="bg-surface-1 border border-line rounded-lg px-4 py-3">
            <div className={`font-mono text-2xl font-black ${x.c ?? 'text-ink-1'}`}>{x.v}</div>
            <div className="text-xs text-ink-3 mt-0.5">{x.l}</div>
            {x.sub && <div className="text-[10px] text-ink-4 mt-0.5">{x.sub}</div>}
          </div>
        ))}
      </div>

      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <h3 className="text-xs font-semibold text-ink-3 flex items-center gap-1.5 mb-3">
          <MessageCircle className="w-3.5 h-3.5" /> Audiência do WhatsApp
        </h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { l: 'Com telefone', v: d.usuarios.com_telefone, sub: 'coletado no cadastro' },
            { l: 'Com opt-in',   v: d.usuarios.com_opt_in,   sub: 'autorizaram receber',
              c: d.usuarios.com_opt_in === 0 ? 'text-red-400' : 'text-green-400' },
            { l: 'Picks do dia', v: d.whatsapp.picks_do_dia, sub: '1 por dia' },
            { l: 'Reengajamento', v: d.whatsapp.reengajamento, sub: 'sumidos com opt-in' },
          ].map(x => (
            <div key={x.l} className="bg-surface-2 rounded-md px-3 py-2">
              <div className={`font-mono text-lg font-black ${x.c ?? 'text-ink-1'}`}>{x.v}</div>
              <div className="text-[10px] text-ink-3">{x.l}</div>
              <div className="text-[10px] text-ink-4">{x.sub}</div>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-ink-4 mt-3 leading-relaxed">
          O aviso de resultado alcançaria {d.whatsapp.resultado} pessoas, contando só quem
          seguiu pick nos últimos 30 dias. Ele é o único dos três que não vai pra base toda,
          e por isso é o mais barato e o menos sujeito a reclamação.
        </p>

        {(d.usuarios.com_opt_in === 0 || !d.whatsapp.envio_ativo) && (
          <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/[0.07] px-3 py-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-ink-2 leading-relaxed">
              Nenhuma mensagem sai ainda: o envio não foi implementado e ninguém deu opt-in.
              O telefone do cadastro foi coletado pra conta, não pra marketing, então
              disparar pra essa base sem consentimento é o caminho mais curto pro número ser
              banido. Falta o toggle no perfil e a autorização da Meta para vertical de aposta.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
