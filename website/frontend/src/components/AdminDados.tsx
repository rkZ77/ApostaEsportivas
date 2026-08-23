import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Database, RefreshCw } from 'lucide-react'
import api from '../services/api'
import { Button, SpinnerBlock, StatTile } from './ui'

/*
 * O que o motor tem pra ler, e onde estão os buracos.
 *
 * A aba Pipeline responde "o sistema está de pé". Esta responde outra coisa:
 * "o motor está enxergando?". São perguntas diferentes, e a segunda não tinha
 * tela · jogo encerrado sem estatística não quebra nada, só deixa a média
 * velha, e média velha não parece defeito de coisa nenhuma.
 *
 * O número que manda aqui é o de partidas encerradas sem estatística. Ele é a
 * distância entre o que aconteceu no mundo e o que o motor sabe.
 */

interface Dados {
  contagem: Record<string, number | null>
  frescor: { ultima_partida?: string | null; ultimos_7_dias?: number | null }
  buracos: { total?: number | null; mais_antigo?: string | null }
  por_liga: {
    league_id: number; name: string; ativa: boolean
    com_estatistica: number; ultima: string | null
  }[]
  varredura: {
    habilitada?: boolean; intervalo_s?: number; janela_dias?: number
    rodando?: boolean; ultima_passada_ha_s?: number | null
    ultimo_resultado?: unknown; erro?: string
  }
}

const numero = (v: number | null | undefined) =>
  v == null ? '·' : v.toLocaleString('pt-BR')

/** "2026-08-22T21:30:00" -> "22/08". Fatiado, nunca por `new Date`: as datas
 *  deste banco já estão em Brasília e qualquer parse reintroduz fuso. */
const diaMes = (iso?: string | null) => {
  if (!iso) return '·'
  const [a, m, d] = iso.slice(0, 10).split('-')
  return d && m ? `${d}/${m}` : a
}

export default function AdminDados() {
  const [dados, setDados] = useState<Dados | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')

  const buscar = () => {
    setCarregando(true)
    setErro('')
    api.get('/admin/dados')
      .then(r => setDados(r.data))
      .catch(e => setErro(e?.response?.data?.detail ?? 'Não deu pra ler o estado do banco.'))
      .finally(() => setCarregando(false))
  }

  useEffect(buscar, [])

  if (carregando && !dados) return <SpinnerBlock className="py-20" />
  if (erro) return <p className="text-red-400 text-sm py-8">{erro}</p>
  if (!dados) return null

  const buracos = dados.buracos?.total ?? 0
  const v = dados.varredura ?? {}

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-bold text-ink-1">
          <Database className="w-4 h-4" />
          Dados no banco
        </h2>
        <Button size="sm" variant="ghost" onClick={buscar} disabled={carregando}>
          <RefreshCw className={`w-3.5 h-3.5 ${carregando ? 'animate-spin' : ''}`} />
          Atualizar
        </Button>
      </div>

      {/* O buraco vem primeiro porque é o único número acionável da tela. */}
      <div className={`card p-4 border ${buracos > 0 ? 'border-yellow-500/40 bg-yellow-500/5' : 'border-line'}`}>
        <div className="flex items-start gap-3">
          {buracos > 0
            ? <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0 mt-0.5" />
            : <CheckCircle2 className="w-5 h-5 text-green-400 shrink-0 mt-0.5" />}
          <div>
            <p className="text-sm font-bold text-ink-1">
              {buracos > 0
                ? `${numero(buracos)} partida(s) encerrada(s) sem estatística`
                : 'Toda partida encerrada tem estatística'}
            </p>
            <p className="text-[11px] text-ink-3 mt-1 leading-relaxed">
              {buracos > 0 ? (
                <>
                  É a distância entre o que aconteceu e o que o motor sabe · sem a linha
                  em <span className="font-mono">match_statistics</span>, o jogo não entra
                  em baseline de liga, média de time, média de árbitro nem confronto direto.
                  {dados.buracos?.mais_antigo && ` Mais antigo: ${diaMes(dados.buracos.mais_antigo)}.`}
                </>
              ) : (
                'O motor está lendo tudo que já foi apitado dentro da janela coletada.'
              )}
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <StatTile label="Jogos coletados"  value={numero(dados.contagem?.fixtures)} />
        <StatTile label="Com estatística"  value={numero(dados.contagem?.match_statistics)} tone="green" />
        <StatTile label="Médias por time"  value={numero(dados.contagem?.team_statistics)} />
        <StatTile label="Times"            value={numero(dados.contagem?.teams)} />
        <StatTile label="Últimos 7 dias"   value={numero(dados.frescor?.ultimos_7_dias)}
          hint="partidas com estatística" />
        <StatTile label="Última partida lida" value={diaMes(dados.frescor?.ultima_partida)} />
        <StatTile label="Picks VIP"        value={numero(dados.contagem?.picks_vip)} />
        <StatTile label="Picks free"       value={numero(dados.contagem?.picks_free)} />
      </div>

      {/* Coleta automática · o que substituiu o clique manual. */}
      <div className="card p-4">
        <h3 className="text-sm font-bold text-ink-1 mb-2">Coleta automática</h3>
        {v.erro ? (
          <p className="text-[11px] text-red-400">{v.erro}</p>
        ) : (
          <>
            <p className="text-[11px] text-ink-3 leading-relaxed">
              {v.habilitada
                ? <>Ligada · roda no máximo a cada {Math.round((v.intervalo_s ?? 600) / 60)} min,
                    e só quando há jogo encerrado sem estatística nos últimos {v.janela_dias} dias.</>
                : <>Desligada neste ambiente. Ela só roda em produção · a chave da API é uma
                    conta só para os três ambientes, então dev consumiria a cota do site real.</>}
            </p>
            <div className="flex items-center gap-4 mt-2 text-[11px] font-mono text-ink-4">
              <span>{v.rodando ? 'rodando agora' : 'ociosa'}</span>
              {v.ultima_passada_ha_s != null && (
                <span>última passada há {Math.round(v.ultima_passada_ha_s / 60)} min</span>
              )}
            </div>
            {v.ultimo_resultado != null && (
              <pre className="mt-2 text-[10px] text-ink-4 bg-surface-2 rounded p-2 overflow-x-auto">
                {JSON.stringify(v.ultimo_resultado)}
              </pre>
            )}
          </>
        )}
      </div>

      {/* Por liga · onde o buraco mora, quando existe. */}
      <div className="card p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-line">
          <h3 className="text-sm font-bold text-ink-1">Histórico por liga</h3>
          <p className="text-[11px] text-ink-4 mt-0.5">
            Liga encerrada continua aqui de propósito: o histórico dela sustenta a calibração,
            mesmo sem gerar pick.
          </p>
        </div>
        <div className="divide-y divide-line/60">
          {(dados.por_liga ?? []).map(l => (
            <div key={l.league_id} className="flex items-center gap-3 px-4 py-2.5">
              <span className="flex-1 min-w-0">
                <span className="block text-sm text-ink-2 font-semibold truncate">{l.name}</span>
                {!l.ativa && <span className="text-[10px] text-ink-4">só histórico</span>}
              </span>
              <span className="font-mono text-[11px] text-ink-4 shrink-0">
                última {diaMes(l.ultima)}
              </span>
              <span className={`font-mono text-sm font-black shrink-0 w-16 text-right ${
                l.com_estatistica > 0 ? 'text-ink-2' : 'text-red-400'}`}>
                {numero(l.com_estatistica)}
              </span>
            </div>
          ))}
        </div>
        <p className="px-4 py-2.5 text-[10px] text-ink-4 border-t border-line/60">
          O número é de partidas com estatística gravada. Liga cadastrada com zero é liga que
          nunca coletou · quase sempre falta rodar "Coletar" na aba Ligas.
        </p>
      </div>
    </div>
  )
}
