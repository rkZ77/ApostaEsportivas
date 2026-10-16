import NumberFlow from '@number-flow/react'

/*
 * NÚMERO QUE MUDA NA FRENTE DA PESSOA (15/10/2026, identidade visual).
 *
 * Odd ao vivo, placar e minuto trocavam seco. Aqui cada dígito rola como num
 * placar eletrônico (NumberFlow). Só pra número que muda enquanto a tela está
 * aberta · número parado (resumo, histórico) não ganha nada com isso, e a Home
 * fica sem a biblioteca pra continuar leve. Respeita "reduzir movimento" do
 * aparelho sozinho.
 */
export default function NumeroVivo({ valor, casas = 0, className }: {
  valor: number | null | undefined
  /** Casas decimais fixas (odd = 2, placar = 0). */
  casas?: number
  className?: string
}) {
  if (valor == null || !Number.isFinite(valor)) return <span className={className}>-</span>
  return (
    <NumberFlow
      value={valor}
      className={className}
      locales="en-US"
      format={{ minimumFractionDigits: casas, maximumFractionDigits: casas, useGrouping: false }}
    />
  )
}
