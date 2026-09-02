import { Badge } from './ui'

/*
 * A AMOSTRA · quais jogos o motor leu, em formato de tela.
 *
 * ARQUIVO PRÓPRIO POR CAUSA DO BUNDLE, não por organização. Este bloco é usado
 * em dois lugares muito diferentes:
 *
 *   · AdminAuditoriaMotores · painel do admin, carregado por 1 pessoa;
 *   · AmostraDoMotor · dentro do "Entenda esta análise", carregado por TODO
 *     assinante que abre um pick.
 *
 * Enquanto ele morava dentro do componente de admin, importá-lo no modal
 * puxava o painel inteiro (tabelas de execução, filtros, chamadas de
 * /admin/*) para o chunk que o usuário comum baixa. É o mesmo erro de
 * code-splitting que o blog já cometeu ao juntar meta e componente num
 * arquivo só.
 *
 * O que ele desenha vem de services/engine_audit/amostra.py, gravado pelo
 * motor no instante da escolha. Nenhum número é calculado aqui.
 */

interface JogoDaAmostra {
  data: string | null
  adversario: string | null
  mando: string
  gols_pro: number | null
  gols_contra: number | null
  gols_total: number | null
  gols_ht: number | null
  league_id: number | null
}

interface LadoDaAmostra {
  time: string | null
  jogos_lidos: number
  jogos_exibidos: number
  multi_competicao: boolean
  jogos: JogoDaAmostra[]
}

export interface Amostra {
  max_exibidos?: number
  mandante?: LadoDaAmostra
  visitante?: LadoDaAmostra
  /** Prop de jogador guarda outra forma: uma lista de valores por atuação. */
  valores?: number[]
  atuacoes_lidas?: number
  /* O endpoint devolve estes três no pick de jogador (metodo, linha e nome).
     São a reserva de quem abre a amostra sem o card por perto. */
  mercado?: string
  jogador?: string
  linha?: number
  confronto?: {
    descricao?: string | null
    fase?: string | null
    is_mata_mata?: boolean
    is_jogo_de_volta?: boolean
    leg_origem?: string | null
    is_classico?: boolean
    rivalidade_label?: string | null
    rivalidade_confrontos?: number | null
    jogo_de_ida?: { data: string | null; gols_mandante_atual: number | null; gols_visitante_atual: number | null }
    agregado?: { diferenca: number | null; gols_para_reverter: number | null; lider: string | null }
  } | null
}

const diaMes = (iso?: string | null) => {
  if (!iso) return '-'
  const [a, m, d] = iso.slice(0, 10).split('-')
  return d && m ? `${d}/${m}` : a
}

export default function BlocoAmostra({ amostra, mercado, jogador, linha }: {
  amostra: Amostra
  mercado?: string
  jogador?: string
  linha?: number
}) {
  const lados = [amostra.mandante, amostra.visitante].filter(Boolean) as LadoDaAmostra[]
  const c = amostra.confronto
  const valores = amostra.valores ?? []
  // Quantas atuações bateram a linha. É a mesma conta que o motor fez
  // (`frequencia` no pipeline), refeita aqui só sobre o que está na tela · por
  // isso o rótulo diz "das N exibidas", e não "das N lidas".
  const bateram = linha != null ? valores.filter(v => v >= linha).length : null

  return (
    <div className="space-y-3">
      {/* O contexto do confronto vem ANTES dos jogos. Ele é o que muda a
        * leitura de todos eles: dez jogos de um time que está num agregado de
        * 3x0 não descrevem o jogo de hoje da mesma forma. */}
      {c && (c.descricao || c.is_classico || c.is_mata_mata) && (
        <div className="bg-surface-0 border border-line rounded-lg p-3 space-y-1.5">
          <div className="flex flex-wrap gap-1.5">
            {c.is_classico && <Badge tone="amber">Clássico</Badge>}
            {c.is_mata_mata && <Badge tone="neutral">{c.fase ?? 'Mata-mata'}</Badge>}
            {c.is_jogo_de_volta && (
              <Badge tone="neutral">
                Jogo de volta{c.leg_origem === 'inferido' ? ' (inferido)' : ''}
              </Badge>
            )}
          </div>
          {c.jogo_de_ida && (
            <p className="text-[11px] text-ink-2">
              Ida: {c.jogo_de_ida.gols_mandante_atual} x {c.jogo_de_ida.gols_visitante_atual}
              {c.agregado?.gols_para_reverter
                ? `, faltam ${c.agregado.gols_para_reverter} gol(s) para virar o agregado`
                : ''}
            </p>
          )}
          {c.descricao && <p className="text-[11px] text-ink-3 leading-relaxed">{c.descricao}</p>}
          {c.is_classico && c.rivalidade_confrontos != null && (
            <p className="text-[10px] text-ink-4">
              Rivalidade medida em {c.rivalidade_confrontos} confronto(s) diretos, é excesso de
              cartão sobre a linha de base, não rótulo.
            </p>
          )}
        </div>
      )}

      {/* PROP DE JOGADOR: uma fileira de números, não dois times.
        *
        * E a fileira sozinha não se lê. "3 2 1 4 2 2 0 3 2 1" só vira
        * informação com o cabeçalho que diz de que MERCADO são e qual LINHA
        * precisava ser batida · aí cada número se classifica sozinho, e o
        * verde/cinza mostra a frequência sem precisar contar na mão.
        *
        * Sem a linha (pick antigo, ou amostra aberta fora do card) o bloco
        * continua igual ao que era: os números crus, sem cor inventada. */}
      {valores.length > 0 && (
        <div className="bg-surface-0 border border-line rounded-lg overflow-hidden">
          {(mercado || linha != null) && (
            <div className="px-3 py-2 border-b border-line space-y-0.5">
              {jogador && (
                <div className="flex items-baseline gap-2">
                  <span className="w-[3.75rem] shrink-0 text-[10px] text-ink-4">Jogador</span>
                  <span className="text-xs font-bold text-ink-1 truncate">{jogador}</span>
                </div>
              )}
              {mercado && (
                <div className="flex items-baseline gap-2">
                  <span className="w-[3.75rem] shrink-0 text-[10px] text-ink-4">Mercado</span>
                  <span className="text-xs font-semibold text-ink-2 truncate">{mercado}</span>
                </div>
              )}
              {linha != null && (
                <div className="flex items-baseline gap-2">
                  <span className="w-[3.75rem] shrink-0 text-[10px] text-ink-4">Linha</span>
                  <span className="text-xs text-ink-2">{linha} ou mais</span>
                </div>
              )}
            </div>
          )}
          <div className="p-3">
            <div className="text-[10px] text-ink-4 mb-1.5">
              Últimas atuações{amostra.atuacoes_lidas ? `, ${valores.length} de ${amostra.atuacoes_lidas} lidas` : ''}
              {', da mais recente para a mais antiga'}
            </div>
            <div className="flex flex-wrap gap-1">
              {valores.map((v, i) => {
                const bateu = linha != null && v >= linha
                return (
                  <span
                    key={i}
                    title={linha == null ? undefined
                      : bateu ? `${v}, bateu a linha` : `${v}, não bateu`}
                    className={`font-mono text-xs rounded px-1.5 py-0.5 tabular-nums border ${
                      linha == null
                        ? 'bg-surface-2 text-ink-1 border-transparent'
                        : bateu
                          ? 'bg-green-500/10 text-green-400 border-green-500/25'
                          : 'bg-surface-2 text-ink-4 border-line'}`}
                  >
                    {v}
                  </span>
                )
              })}
            </div>
            {bateram != null && (
              <p className="text-[10px] text-ink-4 mt-2">
                {bateram} das {valores.length} atuações exibidas bateram a linha de {linha} ou mais.
              </p>
            )}
          </div>
        </div>
      )}

      {lados.map(lado => (
        <div key={lado.time ?? Math.random()} className="bg-surface-0 border border-line rounded-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-line flex flex-wrap items-baseline justify-between gap-1">
            <span className="text-xs font-bold text-ink-1">{lado.time ?? 'Time'}</span>
            <span className="text-[10px] text-ink-4">
              {lado.jogos_exibidos} de {lado.jogos_lidos} jogos lidos
              {/* Ler todas as competições é o recorte que o motor usa em copa e
                * seleção. Dizer isso na tela evita a leitura errada de "ele
                * misturou competição": ele misturou de propósito. */}
              {lado.multi_competicao && ', todas as competições'}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] min-w-[22rem]">
              <thead>
                <tr className="text-ink-4 text-[10px] border-b border-line">
                  <th className="text-left font-medium px-3 py-1.5">Data</th>
                  <th className="text-left font-medium px-2 py-1.5">Adversário</th>
                  <th className="text-center font-medium px-2 py-1.5">Mando</th>
                  <th className="text-right font-medium px-2 py-1.5">Placar</th>
                  <th className="text-right font-medium px-3 py-1.5">HT</th>
                </tr>
              </thead>
              <tbody>
                {lado.jogos.map((j, i) => (
                  <tr key={i} className="border-b border-line/50 last:border-0">
                    <td className="px-3 py-1.5 text-ink-3 font-mono tabular-nums">{diaMes(j.data)}</td>
                    <td className="px-2 py-1.5 text-ink-2 truncate max-w-[10rem]">{j.adversario ?? '-'}</td>
                    <td className="px-2 py-1.5 text-center text-ink-4">
                      {j.mando === 'casa' ? 'Casa' : 'Fora'}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink-1">
                      {j.gols_pro ?? '-'}-{j.gols_contra ?? '-'}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-ink-3">
                      {j.gols_ht ?? '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  )
}
