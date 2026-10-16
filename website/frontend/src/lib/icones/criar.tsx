import { forwardRef, type ForwardRefExoticComponent, type RefAttributes, type SVGProps } from 'react'

/*
 * OS ÍCONES DO SITE (15/10/2026, identidade visual).
 *
 * Saiu o lucide (o ícone padrão de todo template de IA) e entrou o desenho do
 * Phosphor (MIT, phosphoricons.com), que tem mais personalidade. A biblioteca
 * NÃO vai pro navegador: cada ícone dela carrega seis pesos, e com os ~117 do
 * site o pacote principal ia de 232 KB pra 551 KB. scripts/gerar-icones.mjs
 * extrai só os pesos usados e escreve UM ARQUIVO POR ÍCONE nesta pasta, pra
 * cada um ir só no pedaço da tela que o usa (a Home leva só os dela).
 *
 * O apelido de cada ícone é o nome que o site já usava (do lucide), então as
 * telas só trocaram a linha de import. O mapa apelido -> Phosphor é mapa.json.
 *
 * O que este desenhista traduz do jeito lucide:
 *  - `strokeWidth` 2.5 ou mais vira o peso 'bold' (quando o ícone tem);
 *  - classe `fill-...` (estrela de favorito preenchida) vira o peso 'fill';
 *  - tamanho padrão 24, igual ao lucide (a classe w-/h- continua mandando).
 */

export type PesoDoIcone = 'regular' | 'bold' | 'fill'
export type DesenhoDoIcone = Partial<Record<PesoDoIcone, string>>

export interface IconeProps extends Omit<SVGProps<SVGSVGElement>, 'ref'> {
  size?: number | string
  /** Herança do lucide: 2.5+ vira traço grosso (se o ícone tiver 'bold'). */
  strokeWidth?: number | string
  absoluteStrokeWidth?: boolean
  weight?: PesoDoIcone
}
export type LucideIcon = ForwardRefExoticComponent<IconeProps & RefAttributes<SVGSVGElement>>

export function criarIcone(apelido: string, desenhos: DesenhoDoIcone): LucideIcon {
  const C = forwardRef<SVGSVGElement, IconeProps>(function Icone(
    { strokeWidth, absoluteStrokeWidth: _a, weight, size, className, ...resto }, ref,
  ) {
    const pedido: PesoDoIcone = weight
      ?? (typeof className === 'string' && /(^|\s)fill-(?!none\b)/.test(className) ? 'fill'
        : Number(strokeWidth ?? 2) >= 2.5 ? 'bold' : 'regular')
    const html = desenhos[pedido] ?? desenhos.regular ?? ''
    const lado = size ?? 24
    return (
      <svg ref={ref} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width={lado} height={lado}
        fill="currentColor" className={className} aria-hidden={resto['aria-label'] ? undefined : true}
        {...resto} dangerouslySetInnerHTML={{ __html: html }} />
    )
  })
  C.displayName = apelido
  return C
}
