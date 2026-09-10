import SelectMenu from './ui/SelectMenu'

/*
 * A BARRA DE CONTROLES DE UMA LISTA DE PICKS · uma só, para todas as abas.
 *
 * Ela morava dentro de pages/Picks.tsx e por isso a aba Ao Vivo, que tem
 * componente próprio, não tinha filtro nenhum -- ficava com dez cards
 * encerrados e nenhum jeito de olhar só os GREEN. Aqui ela serve as duas.
 *
 * O CAMPO DE BUSCA NÃO EXISTE (07/09, decisão do usuário). Ele só existia na
 * aba VIP, e era o que fazia aquela barra ser diferente de todas as outras
 * -- além de esticar até passar da largura da grade no desktop. Liga,
 * resultado e ordem respondem as mesmas perguntas com três menus iguais aos
 * do filtro de mês dos Resultados.
 */
export type OrdemDePick = 'rank' | 'prob' | 'odd' | 'hora'

export default function FiltrosDePicks({
  picks, liga, setLiga, resultado, setResultado, ordem, setOrdem, mostrados,
}: {
  picks: any[]
  liga: string; setLiga: (v: string) => void
  resultado: string; setResultado: (v: string) => void
  ordem?: OrdemDePick; setOrdem?: (v: OrdemDePick) => void
  /** Quantos sobraram depois do filtro · só aparece com filtro ativo. */
  mostrados?: number
}) {
  const ligas = Array.from(new Set(picks.map(p => p.league_name).filter(Boolean))) as string[]
  if (picks.length < 2) return null

  const porLiga = (lg: string) => picks.filter(p => p.league_name === lg).length
  const ativo = Boolean(liga || resultado)

  return (
    /* O RESPIRO E' DAQUI, e nao de cada aba (10/09/2026).
     *
     * A barra aparece em sete telas e em nenhuma delas tinha margem embaixo:
     * os cards comecavam colados nos seletores, e o filtro parecia parte do
     * primeiro card em vez de um controle da lista. Corrigir em sete lugares
     * seria sete chances de esquecer o oitavo. */
    <div className="flex flex-wrap items-center gap-2 mb-4">
      {ligas.length > 1 && (
        <SelectMenu
          ariaLabel="Liga"
          options={[{ value: '', label: 'Todas as ligas' },
                    ...ligas.map(lg => ({ value: lg, label: lg, meta: String(porLiga(lg)) }))]}
          value={liga}
          onChange={setLiga}
        />
      )}
      <SelectMenu
        ariaLabel="Resultado"
        options={[
          { value: '', label: 'Todos os resultados' },
          { value: 'pending', label: 'Pendentes' },
          { value: 'GREEN', label: 'Green' },
          { value: 'RED', label: 'Red' },
        ]}
        value={resultado}
        onChange={setResultado}
      />
      {setOrdem && (
        <SelectMenu
          ariaLabel="Ordenar"
          options={[
            { value: 'rank', label: 'Ordem do motor' },
            { value: 'prob', label: 'Maior probabilidade' },
            { value: 'odd', label: 'Maior odd' },
            { value: 'hora', label: 'Horário do jogo' },
          ]}
          value={ordem ?? 'rank'}
          onChange={v => setOrdem(v as OrdemDePick)}
        />
      )}
      {ativo && (
        <button
          onClick={() => { setLiga(''); setResultado('') }}
          className="text-[11px] font-bold text-accent-ink hover:text-accent-hover transition-colors"
        >
          Limpar
        </button>
      )}
      {ativo && mostrados != null && (
        <span className="text-[11px] text-ink-4">{mostrados} de {picks.length}</span>
      )}
    </div>
  )
}

/** Aplica liga + resultado, na ordem em que a tela oferece. */
export function filtrarPicks(picks: any[], liga: string, resultado: string): any[] {
  return picks.filter(p => {
    if (liga && p.league_name !== liga) return false
    if (!resultado) return true
    return resultado === 'pending' ? !p.result : p.result === resultado
  })
}

/** Reordena sem filtrar. `rank` devolve a lista como o motor entregou. */
export function ordenarPicks(picks: any[], ordem: OrdemDePick): any[] {
  if (ordem === 'rank') return picks
  return [...picks].sort((a, b) => {
    if (ordem === 'prob') return Number(b.probability ?? b.confidence ?? 0) - Number(a.probability ?? a.confidence ?? 0)
    if (ordem === 'odd') return Number(b.odd ?? 0) - Number(a.odd ?? 0)
    // horário: sem match_datetime o pick vai pro fim, não pro topo.
    const ha = a.match_datetime ? String(a.match_datetime).slice(11, 16) : '99:99'
    const hb = b.match_datetime ? String(b.match_datetime).slice(11, 16) : '99:99'
    return ha.localeCompare(hb)
  })
}
