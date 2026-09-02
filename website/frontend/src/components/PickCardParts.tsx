import { BrainCircuit, Check as CheckIcon, Loader2, Share2 } from 'lucide-react'
import { cn } from '../lib/cn'

/*
 * Peças comuns dos cards de pick.
 *
 * Existem cinco cards (VIP, free, múltipla, alavancagem e mercados) e cada um
 * tinha desenhado o próprio rodapé, a própria barra de confiança e a própria
 * faixa de números. Resultado: o mesmo botão "Apostar" com três raios de
 * borda diferentes, e o card de mercados sem botão nenhum.
 *
 * Não virou um componente único com vinte props condicionais de propósito: as
 * diferenças entre os tipos são reais (múltipla tem N seleções, alavancagem
 * tem progressão de banca, mercados tem nome de goleiro). O que se unifica é
 * a ANATOMIA, não o conteúdo.
 */

/* ── Rodapé ─────────────────────────────────────────────────────────────── */

export function PickCardFooter({
  /** Ação principal. Ausente em pick já resolvido. */
  onBet,
  betState = 'idle',
  /** Sem banca configurada o botão vira convite pra configurar. */
  hasBanca = true,
  onShare,
  shareState = 'idle',
  className,
}: {
  onBet?: (e: React.MouseEvent) => void
  betState?: 'idle' | 'loading' | 'done'
  hasBanca?: boolean
  onShare?: (e: React.MouseEvent) => void
  shareState?: 'idle' | 'loading' | 'done'
  className?: string
}) {
  const betLabel =
    betState === 'loading' ? 'Registrando...'
    : betState === 'done' ? 'Registrado'
    : hasBanca ? 'Apostar'
    : 'Configurar banca'

  return (
    <div className={cn('flex items-center gap-2 px-5 py-3 border-t border-line/60 mt-auto', className)}>
      {onBet && (
        <button
          onClick={onBet}
          disabled={betState !== 'idle'}
          /* Âncora do tour: o passo "Registre sua aposta" destaca este botão
             de verdade, no primeiro card da tela. Ver
             components/onboarding/steps.tsx. */
          data-tour="pick-apostar"
          className={cn(
            'text-xs font-bold px-3 py-2 rounded-md border transition-colors duration-1 ease-smooth min-h-[36px]',
            betState === 'done'
              ? 'border-accent/30 text-accent-ink bg-accent/10 cursor-default'
              : hasBanca
              ? 'border-accent/30 text-accent-ink bg-accent/10 hover:bg-accent/20'
              : 'border-yellow-500/30 text-yellow-400 hover:border-yellow-500/60 hover:bg-yellow-500/5',
          )}
        >
          {betLabel}
        </button>
      )}

      <div className="flex items-center gap-2 ml-auto">
        {onShare && (
          <button
            onClick={onShare}
            disabled={shareState === 'loading'}
            title="Compartilhar pick"
            className="flex items-center gap-1.5 text-xs font-semibold text-ink-2 hover:text-accent-ink border border-line-strong hover:border-accent/50 px-3 py-2 rounded-md transition-colors duration-1 ease-smooth disabled:opacity-60 min-h-[36px]"
          >
            {shareState === 'loading'
              ? <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
              : shareState === 'done'
              ? <CheckIcon className="w-3.5 h-3.5 text-accent-ink shrink-0" />
              : <Share2 className="w-3.5 h-3.5 shrink-0" />}
            <span className="hidden sm:inline">
              {shareState === 'loading' ? 'Gerando...' : shareState === 'done' ? 'Pronto' : 'Compartilhar'}
            </span>
          </button>
        )}
      </div>
    </div>
  )
}

/* ── Entenda esta análise ───────────────────────────────────────────────── */

/**
 * Botão largo, no corpo do card e não no rodapé.
 *
 * Fica no meio de propósito: é a ação de LEITURA, e o rodapé é a fila de ação
 * (apostar, compartilhar). Largura cheia porque, espremido ao lado dos outros
 * dois, o rótulo tinha que virar só "Entenda" pra caber no celular, e aí a
 * frase perdia o convite.
 */
export function PickExplainButton({
  onClick,
  onIntencao,
  className,
}: {
  onClick: (e: React.MouseEvent) => void
  /** O DEDO ENCOSTANDO JÁ VALE COMO PEDIDO.
   *
   *  A análise é uma requisição ao servidor, e buscá-la só no clique faz o
   *  modal abrir vazio e ir se preenchendo. `pointerdown` no celular acontece
   *  de 100 a 300ms antes do clique, e `pointerenter` no desktop bem antes
   *  disso · nesse tempo a resposta costuma chegar, e o modal abre pronto.
   *
   *  Quem passa isto adianta a busca (ver services/analisePick). Sem a prop, o
   *  botão continua sendo só um botão. */
  onIntencao?: () => void
  className?: string
}) {
  return (
    <div className={cn('px-5 pb-3', className)}>
      <button
        onPointerEnter={onIntencao}
        onPointerDown={onIntencao}
        onFocus={onIntencao}
        onClick={e => { e.stopPropagation(); onClick(e) }}
        className="w-full flex items-center justify-center gap-1.5 text-[11px] font-semibold text-ink-2 hover:text-ink-1 border border-line hover:border-line-strong rounded-md py-2.5 min-h-[36px] transition-colors duration-1 ease-smooth"
      >
        <BrainCircuit className="w-3.5 h-3.5 shrink-0" />
        Entenda esta análise
      </button>
    </div>
  )
}

/* ── Probabilidade ──────────────────────────────────────────────────────── */

/**
 * Probabilidade estimada do pick sair.
 *
 * Chamava-se "confiança" e mostrava o campo `confidence`, que e' OUTRO numero:
 * medido no banco, confidence vem sistematicamente ACIMA de probability (0,816
 * contra 0,755 no mesmo pick). Exibir confidence sob o rotulo "probabilidade"
 * seria dizer 82% onde a chance calculada e' 75%.
 *
 * Entao le `probability` de verdade, e so' cai em `confidence` quando nao ha
 * probabilidade nenhuma: picks VIP antigos (42 de 149 sem o campo) e multiplas,
 * que nao tem coluna de probabilidade.
 *
 * Os cortes (75 e 60) sao os mesmos do resto do site pra decidir cor.
 */
export function PickProbability({
  confidence,
  probability,
  label = 'Probabilidade',
  className,
}: {
  /** Fração 0..1. Só é usada quando não há probabilidade. */
  confidence?: number | null
  /** Fração 0..1. É esta que o rótulo promete. */
  probability?: number | null
  /**
   * Rótulo à esquerda. Só a múltipla muda ("Probabilidade combinada"), porque
   * ali o número é de fato outra quantidade -- o produto das pernas, não a
   * chance de um mercado só. Cor, escala e cortes seguem iguais aos do VIP.
   */
  label?: string
  className?: string
}) {
  const bruto = probability ?? confidence
  if (bruto == null) return null
  const pct = Math.round(Number(bruto) * 100)
  // Sem probabilidade real, o numero e' uma aproximacao: o rotulo avisa.
  const aproximado = probability == null

  return (
    <div className={cn('px-5 pb-3', className)}>
      <div className="flex justify-between items-baseline text-[10px] mb-1">
        <span className="text-ink-4">
          {label}{aproximado && <span className="text-ink-4"> estimada</span>}
        </span>
        <span className={cn('font-mono', pct >= 75 ? 'text-accent-ink font-bold' : 'text-ink-3')}>
          {pct}%
        </span>
      </div>
      <div className="bg-surface-2 rounded-full h-1 overflow-hidden">
        <div
          className={cn(
            'h-1 rounded-full',
            pct >= 75 ? 'bg-accent' : pct >= 60 ? 'bg-yellow-500' : 'bg-ink-4',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

/*
 * A tira de números do topo (odd/stake/lucro/EV) NÃO mora aqui.
 *
 * Existiu um `PickStats` genérico e nenhum dos cinco cards conseguiu usá-lo:
 * o VIP mostra três colunas que mudam conforme o pick foi seguido, resolvido
 * ou está pendente; a múltipla mostra a odd do bilhete; a alavancagem mostra
 * progressão de banca. Espremer isso num componente de lista de itens exigia
 * mais props condicionais do que o markup que ele substituía, e o componente
 * ficou um ano sem chamador. Removido em 2026-08-14.
 *
 * O que se unifica é a ANATOMIA (ordem das seções, respiro, tipografia) — e
 * essa parte é garantida pelas peças abaixo e pela classe `.pick-card`.
 */

/* ── Os campos do pick ──────────────────────────────────────────────────── */

/*
 * "MERCADO: X" E "LINHA: Y", UM POR LINHA, EM TODO CARD DO SITE.
 *
 * Antes cada card escrevia isso do seu jeito e tudo numa linha só, separado por
 * vírgulas: "Gols Mais/Menos , Mais de 1.5 , Betano". Três informações
 * diferentes com o mesmo peso visual e nenhum rótulo, então a leitura dependia
 * de já saber qual é qual · e no celular a linha truncava justamente no fim,
 * que é onde mora a linha da aposta.
 *
 * Rotulado, cada pergunta tem um lugar fixo: o olho desce a coluna dos rótulos
 * e encontra o mesmo campo em qualquer produto, do VIP à perna da múltipla. Foi
 * o desenho que nasceu no pick de jogador (jogador, mercado, linha) e que o
 * usuário pediu para valer no site inteiro em 02/09.
 *
 * A coluna do rótulo é FIXA (`w-[3.75rem]`) de propósito: é ela que alinha os
 * valores entre linhas e entre cards. Com largura automática, "Linha" e
 * "Mercado" empurrariam o valor para posições diferentes em cada card.
 */
export function CampoDoPick({ rotulo, children, className }: {
  rotulo: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-baseline gap-2', className)}>
      <dt className="w-[3.75rem] shrink-0 text-[10px] text-ink-4">{rotulo}</dt>
      {children}
    </div>
  )
}

/* ── O trecho do raciocínio saiu do card em 2026-09-02 ──────────────────── */

/*
 * `PickReasoning` desenhava o "Fato": as primeiras linhas do mesmo `reasoning`
 * que abre dentro do "Entenda esta análise", na seção "Leitura do jogo". Ou
 * seja, o card gastava três linhas de parágrafo para adiantar um texto que
 * está a um toque de distância, e numa lista lida no celular isso empurra o
 * próximo pick para fora da tela.
 *
 * O componente foi removido, não escondido: bloco sem chamador vira código
 * morto e depois volta por engano. Quem quiser o texto abre a análise.
 *
 * O `flex-1` DELE ainda importa e mora agora nos cards. `.pick-card` é
 * `flex flex-col h-full`, e alguém precisa absorver a sobra de altura da
 * grade, senão o rodapé de cada card para onde o conteúdo dele acabar. Cada
 * card tem um `<div className="flex-1" />` no lugar exato onde este bloco
 * ficava.
 */

