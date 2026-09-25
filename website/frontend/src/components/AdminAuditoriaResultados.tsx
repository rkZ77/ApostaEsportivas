import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react'
import api from '../services/api'
import { Spinner } from './ui'

/*
 * Auditoria dos resultados do mês.
 *
 * A pergunta que ela responde é "o que está gravado no mês está certo?", e ela
 * responde sem falar com a API-Football: o bilhete é recombinado a partir das
 * próprias pernas pela mesma função que liquida, e o lucro é conferido contra o
 * que o resultado e a odd obrigam. Por isso ela pode rodar quantas vezes
 * quiser, ao contrário da reconferência, que custa uma requisição por fixture.
 *
 * Ela também não corrige nada. Cada motivo aponta para um botão que já existe:
 * pendência e perna em aberto saem no "Atualizar resultados", divergência de
 * número contra o provedor sai na reconferência, e o resto é caso a caso.
 */

interface Achado {
  pick_type: string
  id: number
  match_date: string | null
  motivo: string
  detalhe: string | null
  gravado: string | number | null
  esperado: string | number | null
}

interface Tipo {
  pick_type: string
  total: number
  pendentes: number
  green: number
  red: number
  push: number
  half_win: number
  half_loss: number
  lucro: number
  problemas: number
}

interface Dados {
  mes: string
  de: string
  ate: string
  folha: boolean
  resumo: {
    total: number; resolvidos: number; pendentes: number
    problemas: number; nao_conferidos: number; lucro: number
  }
  por_tipo: Tipo[]
  por_motivo: Record<string, number>
  por_nao_conferido: Record<string, number>
  achados: Achado[]
}

const ROTULO: Record<string, string> = {
  vip: 'Premium', free: 'Free', multipla: 'Múltipla', bingo: 'Bingo do Dia',
  alavancagem: 'Alavancagem', faltas: 'Faltas', goleiros: 'Defesas',
  player_stats: 'Jogador', boost: 'Pick Boost', live: 'Ao Vivo',
}

// Gravidade do motivo. Quem muda dinheiro (lucro, bilhete que não bate com as
// pernas, seguidor dessincronizado) é vermelho; o resto é âmbar, que é
// pendência de processo e não número errado.
const COR_MOTIVO: Record<string, string> = {
  'não bate com a estatística do jogo':       'text-red-400',
  'perna não bate com a estatística do jogo': 'text-red-400',
  'bilhete não bate com as pernas':   'text-red-400',
  'lucro não bate com as pernas':     'text-red-400',
  'lucro não bate com o resultado':   'text-red-400',
  'seguidor com resultado diferente': 'text-red-400',
  'resultado inválido':               'text-red-400',
  'sem lucro gravado':                'text-red-400',
  'perna sem resultado em bilhete fechado': 'text-amber-400',
  'bilhete fechado sem pernas gravadas':    'text-amber-400',
  'pendente com o jogo encerrado':          'text-amber-400',
}

/** Os últimos seis meses, do corrente para trás, em AAAA-MM de Brasília. */
function ultimosMeses(): string[] {
  const agora = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit',
  }).format(new Date())
  const [ano, mes] = agora.split('-').map(Number)
  const saida: string[] = []
  for (let i = 0; i < 6; i++) {
    const d = new Date(Date.UTC(ano, mes - 1 - i, 1))
    saida.push(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`)
  }
  return saida
}

export default function AdminAuditoriaResultados() {
  const meses = ultimosMeses()
  const [mes, setMes] = useState(meses[0])
  const [dados, setDados] = useState<Dados | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')

  const buscar = useCallback(async (alvo: string) => {
    setCarregando(true)
    setErro('')
    try {
      const { data } = await api.get('/admin/resultados/auditoria', { params: { mes: alvo } })
      setDados(data)
    } catch (e: any) {
      setErro(e.response?.data?.detail || 'Não foi possível auditar o mês agora.')
    } finally {
      setCarregando(false)
    }
  }, [])

  useEffect(() => { buscar(mes) }, [buscar, mes])

  const limpo = dados && dados.resumo.problemas === 0

  return (
    <div className="card p-4 mb-4">
      <div className="flex items-start justify-between gap-3 mb-1">
        <h2 className="text-xs font-semibold text-ink-3">Auditoria de resultados</h2>
        <button onClick={() => buscar(mes)} className="shrink-0 text-ink-4 hover:text-ink-1 transition-colors"
                aria-label="Atualizar">
          <RefreshCw className={`w-3.5 h-3.5 ${carregando ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <p className="text-xs text-ink-3 mb-3 leading-relaxed">
        Refaz a liquidação de cada pick do mês pela folha do jogo já gravada, com
        o mesmo motor que liquidou na origem, e confere o resto contra o próprio
        banco: o bilhete recombinado pelas pernas dele, o lucro contra o resultado
        e a odd, e a lista de quem seguiu dizendo a mesma coisa que o pick. Vale
        para todos os produtos. Não gasta cota da API e não corrige nada, só aponta.
      </p>

      <div className="flex flex-wrap gap-1.5 mb-4">
        {meses.map(m => (
          <button key={m} onClick={() => setMes(m)}
            className={`text-[11px] px-2.5 py-1 rounded-lg border transition-colors touch-manipulation ${
              m === mes
                ? 'border-green-500/50 bg-green-500/10 text-green-400'
                : 'border-line-strong text-ink-2 hover:border-ink-4'}`}>
            {m}
          </button>
        ))}
      </div>

      {erro && <p className="text-xs text-red-400 mb-3">{erro}</p>}

      {carregando && !dados ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : !dados ? null : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              { l: 'Picks no mês', v: dados.resumo.total, sub: `${dados.de} a ${dados.ate}` },
              { l: 'Resolvidos',   v: dados.resumo.resolvidos, sub: `${dados.resumo.pendentes} pendente(s)` },
              { l: 'Problemas',    v: dados.resumo.problemas,
                sub: limpo ? 'nada a corrigir' : 'conferir a lista abaixo',
                c: dados.resumo.problemas > 0 ? 'text-red-400' : 'text-green-400' },
              { l: 'Não conferidos', v: dados.resumo.nao_conferidos,
                sub: 'a folha não respondeu',
                c: dados.resumo.nao_conferidos > 0 ? 'text-amber-400' : 'text-ink-1' },
              { l: 'Lucro gravado', v: `${dados.resumo.lucro > 0 ? '+' : ''}${dados.resumo.lucro.toFixed(2)}u`,
                sub: 'soma do que está no banco',
                c: dados.resumo.lucro >= 0 ? 'text-green-400' : 'text-red-400' },
            ].map(x => (
              <div key={x.l} className="bg-surface-1 border border-line rounded-lg px-4 py-3">
                <div className={`font-mono text-2xl font-black ${x.c ?? 'text-ink-1'}`}>{x.v}</div>
                <div className="text-xs text-ink-3 mt-0.5">{x.l}</div>
                <div className="text-[10px] text-ink-4 mt-0.5">{x.sub}</div>
              </div>
            ))}
          </div>

          {/* Por tipo de pick. Mobile primeiro: no celular vira lista, porque a
              tabela de oito colunas só caberia com rolagem lateral. */}
          <div className="bg-surface-1 border border-line rounded-lg p-4">
            <h3 className="text-xs font-semibold text-ink-3 mb-3">Por produto</h3>
            <ul className="sm:hidden divide-y divide-line/60 -mx-1">
              {dados.por_tipo.filter(t => t.total > 0).map(t => (
                <li key={t.pick_type} className="py-2.5 px-1 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[12px] text-ink-2 font-semibold">{ROTULO[t.pick_type] ?? t.pick_type}</p>
                    <p className="text-[10px] text-ink-4 font-mono mt-0.5">
                      {t.total} picks, {t.green} green, {t.red} red, {t.pendentes} pendente(s)
                    </p>
                  </div>
                  <span className={`text-[11px] font-black shrink-0 ${t.problemas > 0 ? 'text-red-400' : 'text-ink-4'}`}>
                    {t.problemas > 0 ? `${t.problemas} problema(s)` : 'ok'}
                  </span>
                </li>
              ))}
            </ul>
            <div className="hidden sm:block overflow-x-auto -mx-4 px-4">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-ink-4 text-left border-b border-line">
                    <th className="pb-2 font-medium">Produto</th>
                    <th className="pb-2 font-medium">Picks</th>
                    <th className="pb-2 font-medium">Green</th>
                    <th className="pb-2 font-medium">Red</th>
                    <th className="pb-2 font-medium">Anulado</th>
                    <th className="pb-2 font-medium">Pendente</th>
                    <th className="pb-2 font-medium">Lucro</th>
                    <th className="pb-2 font-medium">Problemas</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/60">
                  {dados.por_tipo.filter(t => t.total > 0).map(t => (
                    <tr key={t.pick_type}>
                      <td className="py-2 pr-2 text-ink-2">{ROTULO[t.pick_type] ?? t.pick_type}</td>
                      <td className="py-2 pr-2 text-ink-3 font-mono">{t.total}</td>
                      <td className="py-2 pr-2 text-green-400 font-mono">{t.green + t.half_win}</td>
                      <td className="py-2 pr-2 text-red-400 font-mono">{t.red + t.half_loss}</td>
                      <td className="py-2 pr-2 text-ink-4 font-mono">{t.push}</td>
                      <td className="py-2 pr-2 text-ink-4 font-mono">{t.pendentes}</td>
                      <td className={`py-2 pr-2 font-mono ${t.lucro >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {t.lucro > 0 ? '+' : ''}{t.lucro.toFixed(2)}u
                      </td>
                      <td className={`py-2 font-mono font-bold ${t.problemas > 0 ? 'text-red-400' : 'text-ink-4'}`}>
                        {t.problemas || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {dados.resumo.nao_conferidos > 0 && (
            <div className="bg-surface-1 border border-line rounded-lg p-4">
              <h3 className="text-xs font-semibold text-ink-3 mb-2">
                O que a folha não respondeu
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(dados.por_nao_conferido).map(([motivo, n]) => (
                  <span key={motivo} className="text-[10px] px-2 py-1 rounded-md bg-surface-2 text-ink-3">
                    {motivo}: {n}
                  </span>
                ))}
              </div>
              <p className="text-[10px] text-ink-4 mt-2 leading-relaxed">
                Não é erro de pick: é conferência que não deu pra fazer. Sem folha ou
                folha pela metade pede o coletor de jogos. A folha também não guarda
                quando foi coletada, e o coletor não rebusca partida que já está
                completa, então divergência apontada aqui é suspeita: quem dá a última
                palavra é a reconferência, que pergunta ao provedor.
              </p>
            </div>
          )}

          {limpo ? (
            <div className="flex items-start gap-2 rounded-md border border-green-500/25 bg-green-500/[0.07] px-3 py-2">
              <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0 mt-0.5" />
              <p className="text-[11px] text-ink-2 leading-relaxed">
                Nenhuma divergência em {dados.resumo.total} picks do mês. Todo bilhete
                fechado bate com as pernas dele, e todo lucro bate com o resultado.
              </p>
            </div>
          ) : (
            <div className="bg-surface-1 border border-line rounded-lg p-4">
              <h3 className="text-xs font-semibold text-ink-3 mb-2 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400" /> O que não bate
              </h3>
              <div className="flex flex-wrap gap-1.5 mb-3">
                {Object.entries(dados.por_motivo)
                  .sort((a, b) => b[1] - a[1])
                  .map(([motivo, n]) => (
                    <span key={motivo}
                      className={`text-[10px] px-2 py-1 rounded-md bg-surface-2 ${COR_MOTIVO[motivo] ?? 'text-ink-3'}`}>
                      {motivo}: {n}
                    </span>
                  ))}
              </div>
              <ul className="divide-y divide-line/60 -mx-1">
                {dados.achados.map((a, i) => (
                  <li key={`${a.pick_type}-${a.id}-${i}`} className="py-2 px-1">
                    <div className="flex items-start justify-between gap-2">
                      <span className={`text-[11px] font-semibold ${COR_MOTIVO[a.motivo] ?? 'text-ink-2'}`}>
                        {a.motivo}
                      </span>
                      <span className="text-[10px] text-ink-4 font-mono shrink-0">
                        {ROTULO[a.pick_type] ?? a.pick_type} #{a.id}
                      </span>
                    </div>
                    <p className="text-[10px] text-ink-4 font-mono mt-0.5">
                      {a.match_date ?? 'sem data'}
                      {a.detalhe ? `, ${a.detalhe}` : ''}
                      {a.gravado != null ? `, gravado ${a.gravado}` : ''}
                      {a.esperado != null ? `, esperado ${a.esperado}` : ''}
                    </p>
                  </li>
                ))}
              </ul>
              <p className="text-[10px] text-ink-4 mt-3 leading-relaxed">
                Pendência e perna em aberto costumam sair no botão "Atualizar resultados"
                logo abaixo. Se o número do jogo é que está em dúvida, quem responde é a
                reconferência, que pergunta ao provedor.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
