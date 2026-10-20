/*
 * O BLOCO DE RESULTADO DE UM PICK ENCERRADO, num lugar só (14/10/2026).
 *
 * Os cards Premium (SuggestionCard), Free e múltipla (Picks.tsx) tinham cada
 * um a sua cópia deste bloco, e elas se desencontraram: a coluna "Sua aposta"
 * saiu de um em 07/09 e continuou nos outros dois até 14/10, cortando no
 * celular. Agora os três desenham daqui.
 *
 * As regras que moram aqui:
 *  - "RESULTADO DO PICK", e não "lucro", pra quem não apostou (12/10): o
 *    número é do pick, na stake sugerida, e a linha de baixo diz isso.
 *  - Verde/vermelho só pra quem apostou (14/10): "o site perdeu, eu não".
 *  - "Em reais" só pra quem apostou: real depende de stake, e stake que não
 *    houve não vira dinheiro.
 *  - Produto sem stake de plano (alavancagem) não estampa "+0,00u".
 *
 * Devolve as COLUNAS (fragmento): quem chama já está dentro da faixa do card.
 */
import { calcProfitUnits } from '../utils/stakeUtils'
import { brNum } from '../utils/format'

interface Props {
  result: string
  odd: number
  /** Stake que a pessoa registrou; null = não apostou. */
  stakeSeguida: number | null | undefined
  /** Odd que ela pegou na casa, quando registrou. */
  oddSeguida?: number | null
  /** Stake do plano público pra quem não apostou (stakePlan.stakeDe). */
  stakePlano: number
  /** false = produto que não conta em unidades (alavancagem). */
  contaEmUnidades?: boolean
  banca?: { unit_value: number } | null
}

export default function ResultadoDoPick({
  result, odd, stakeSeguida, oddSeguida, stakePlano, contaEmUnidades = true, banca,
}: Props) {
  const seguiu = stakeSeguida != null
  const contaU = seguiu || contaEmUnidades
  const u = seguiu ? stakeSeguida! : stakePlano
  const p = calcProfitUnits(result, odd, u, seguiu ? oddSeguida : null)
  const color = !seguiu ? 'text-ink-1' : p >= 0 ? 'text-green-400' : 'text-red-400'
  const profitR = seguiu && banca ? Math.abs(p) * banca.unit_value : null
  return (
    <>
      <div className="flex-1 px-4 py-3 text-center">
        <div className="text-[10px] text-ink-3 mb-0.5">{seguiu ? 'Seu lucro' : 'Resultado do pick'}</div>
        {contaU ? (
          <>
            <div className={`text-xl font-black ${color}`}>{p >= 0 ? '+' : ''}{p.toFixed(2)}u</div>
            <div className="text-[10px] text-ink-4 leading-tight">
              {seguiu ? `(${u}u)` : <>stake sugerida {u}u<br />você não apostou</>}
            </div>
          </>
        ) : (
          <>
            <div className="text-xl font-black text-ink-3">-</div>
            <div className="text-[10px] text-ink-4">só conta apostado</div>
          </>
        )}
      </div>
      {seguiu && (
        <div className="flex-1 px-4 py-3 text-center">
          <div className="text-[10px] text-ink-3 mb-0.5">Em reais</div>
          {profitR != null ? (
            <div className={`text-xl font-black ${color}`}>{p >= 0 ? '+' : '-'}R$ {brNum(profitR, 0)}</div>
          ) : (
            <div className="text-xl font-black text-ink-4">-</div>
          )}
        </div>
      )}
    </>
  )
}
