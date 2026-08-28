import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { useOnboarding } from '../../context/OnboardingContext'
import { passosDoTour } from './steps'
import { TOUR_STEPS_VIP } from './stepsVip'
import { TOUR_VIP } from './constantes'
import { cn } from '../../lib/cn'

/*
 * O overlay do onboarding.
 *
 * Três peças que se movem juntas: o véu escuro com um furo, o anel em volta do
 * elemento real e o balão de texto. O véu é um SVG com máscara em vez de quatro
 * divs em volta do buraco · com divs, o canto arredondado do furo não existe e
 * qualquer erro de 1px vira uma fresta clara na diagonal.
 *
 * Duas decisões que valem comentário:
 *
 * 1. O véu CAPTURA clique. O elemento destacado fica visível, não clicável.
 *    Deixá-lo clicável parece generoso até a pessoa apertar "Configurar" no
 *    passo 2 e abrir o modal de banca por cima do tour, com dois diálogos
 *    disputando o foco. Sair continua a um Esc, ou a um clique em "Pular
 *    tutorial", que estão sempre na tela.
 *
 * 2. Alvo que não aparece não trava nada. Procura por até 3s (a página pode
 *    estar carregando os picks) e, não achando, o passo vira um diálogo
 *    centrado com o mesmo texto. Conta nova num dia sem pick publicado é o caso
 *    normal disso, não a exceção.
 */

interface Rect { top: number; left: number; width: number; height: number }

/** Folga entre o elemento real e a borda do furo. */
const FOLGA = 8
/** Distância do balão até o elemento destacado, no desktop. */
const RESPIRO = 14
/** Margem mínima entre o balão e a borda da janela. */
const MARGEM = 12
const LARGURA_BALAO = 380
/** Abaixo disto o balão vira folha presa ao topo ou ao rodapé. */
const CELULAR = 640
/**
 * Fração da tela acima da qual um destaque é "alto".
 *
 * Um card de pick inteiro passa disso num celular. Centralizar um alvo assim
 * deixa pouco espaço dos dois lados, e a folha acaba por cima da parte de CIMA
 * do card · que é onde estão o jogo, o mercado e a odd. Alvo alto é alinhado
 * pelo topo, o que joga todo o espaço livre para baixo, onde a folha mora.
 */
const ALVO_ALTO = 0.45
/** Onde o topo de um alvo alto para, no celular. Barra do site + respiro. */
const TOPO_SEGURO = 88
/** Piso da folha no celular. Abaixo disto ela não cabe nem o próprio cabeçalho. */
const ALTURA_MINIMA = 200
/** Quanto tempo procurar o alvo antes de desistir e centralizar o passo. */
const ESPERA_ALVO_MS = 3000
/**
 * Carência em que SÓ o primeiro alvo da lista conta.
 *
 * Sem ela o tour destacava a coisa errada de forma consistente: os alvos de
 * reserva são as áreas que CONTÊM o preferido, e área existe na tela antes do
 * conteúdo dela. Chegando em /picks com os picks ainda carregando, o card
 * (`pick-card`) ainda não nasceu e a área (`picks-area`) já está lá · o furo
 * saía em volta da página inteira em vez de em volta do card.
 */
const PREFERENCIA_MS = 1200

function mesmoRect(a: Rect | null, b: Rect | null) {
  if (!a || !b) return a === b
  return (
    Math.abs(a.top - b.top) < 1 &&
    Math.abs(a.left - b.left) < 1 &&
    Math.abs(a.width - b.width) < 1 &&
    Math.abs(a.height - b.height) < 1
  )
}

function medir(el: Element): Rect {
  const r = el.getBoundingClientRect()
  return { top: r.top, left: r.left, width: r.width, height: r.height }
}

export default function OnboardingTour() {
  const { aberto, tour, pausado, passo, total, contexto, proximo, voltar, irPara, pular, concluir } = useOnboarding()
  const navigate = useNavigate()
  const { pathname } = useLocation()

  /* O roteiro aberto. O de boas-vindas depende da conta (o passo do e-mail é
     condicional) e `contexto` vem congelado do provider, então a lista não muda
     de tamanho no meio de uma sessão. O do VIP é fixo: quem o vê acabou de
     ganhar acesso a tudo que ele mostra. */
  const passos = useMemo(
    () => (tour === TOUR_VIP ? TOUR_STEPS_VIP : passosDoTour(contexto)),
    [tour, contexto],
  )
  const step = passos[passo]
  const primeiro = passo === 0
  const ultimo = passo === total - 1

  const [rect, setRect] = useState<Rect | null>(null)
  /** null enquanto ainda procura o alvo · evita o balão pular do centro para o canto. */
  const [procurando, setProcurando] = useState(false)
  const [janela, setJanela] = useState(() => ({
    w: typeof window === 'undefined' ? 0 : window.innerWidth,
    h: typeof window === 'undefined' ? 0 : window.innerHeight,
  }))

  const balaoRef = useRef<HTMLDivElement>(null)
  const alvoRef = useRef<Element | null>(null)
  const [alturaBalao, setAlturaBalao] = useState(0)

  const noCelular = janela.w > 0 && janela.w < CELULAR

  /* ── Rota do passo ───────────────────────────────────────────────────────
     Os passos da banca e dos picks só têm o que destacar na página deles. A
     navegação sai daqui e não de dentro dos botões porque o passo também pode
     ser alcançado por retroceder e por reabrir o tour no meio. */
  useEffect(() => {
    if (!aberto || !step?.rota) return
    if (pathname === step.rota) return
    navigate(step.rota)
  }, [aberto, step?.rota, pathname, navigate])

  /* ── Achar o alvo ──────────────────────────────────────────────────────── */
  useEffect(() => {
    alvoRef.current = null
    setRect(null)

    if (!aberto || !step?.alvos?.length) {
      setProcurando(false)
      return
    }
    // Ainda não chegou na rota do passo: não adianta procurar, e desistir aqui
    // faria o passo piscar centrado antes de a página trocar.
    if (step.rota && pathname !== step.rota) {
      setProcurando(true)
      return
    }

    setProcurando(true)
    let vivo = true
    let timer = 0
    const inicio = Date.now()

    const tentar = () => {
      if (!vivo) return
      // Passada a carência, os alvos de reserva entram na disputa.
      const candidatos = Date.now() - inicio > PREFERENCIA_MS
        ? step.alvos!
        : step.alvos!.slice(0, 1)
      const el = candidatos
        .map(sel => document.querySelector(sel))
        .find((n): n is Element => !!n && (n as HTMLElement).offsetParent !== null)

      if (el) {
        alvoRef.current = el
        const r = el.getBoundingClientRect()
        // `innerWidth` direto, e não o estado `janela`: este efeito não tem
        // largura nas dependências, e ler do estado aqui daria o valor de
        // antes de um giro de tela.
        const alvoAlto = window.innerWidth < CELULAR && r.height > window.innerHeight * ALVO_ALTO
        if (alvoAlto) {
          window.scrollBy({ top: r.top - TOPO_SEGURO, behavior: 'smooth' })
        } else {
          el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' })
        }
        // Mede depois que a rolagem assenta. Medir junto com a rolagem devolve
        // a posição de onde o elemento ESTAVA, e o furo nasce fora dele.
        timer = window.setTimeout(() => {
          if (!vivo) return
          setRect(medir(el))
          setProcurando(false)
        }, 340)
        return
      }

      if (Date.now() - inicio > ESPERA_ALVO_MS) {
        setProcurando(false)
        return
      }
      timer = window.setTimeout(tentar, 120)
    }

    tentar()
    return () => { vivo = false; window.clearTimeout(timer) }
  }, [aberto, passo, step, pathname])

  /* ── Manter o furo em cima do alvo ─────────────────────────────────────
     A tela mexe sozinha depois que o passo abre: os dados da banca chegam, o
     card do pick troca de altura, o teclado do celular sobe. Observer pega a
     mudança do elemento, os listeners pegam rolagem e giro de tela, e o
     intervalo lento cobre o resto sem custo perceptível (um
     getBoundingClientRect a cada 400ms). */
  useEffect(() => {
    if (!aberto) return

    const atualizar = () => {
      // Comparado antes de gravar: `atualizar` roda a cada 400ms, e um objeto
      // novo a cada volta re-renderizaria o overlay inteiro duas vezes e meia
      // por segundo sem nada ter mudado na tela.
      setJanela(atual => (
        atual.w === window.innerWidth && atual.h === window.innerHeight
          ? atual
          : { w: window.innerWidth, h: window.innerHeight }
      ))
      const el = alvoRef.current
      if (!el) return
      if (!document.body.contains(el)) {
        alvoRef.current = null
        setRect(null)
        return
      }
      const novo = medir(el)
      setRect(atual => (mesmoRect(atual, novo) ? atual : novo))
    }

    window.addEventListener('resize', atualizar)
    window.addEventListener('scroll', atualizar, true)
    window.addEventListener('orientationchange', atualizar)
    const intervalo = window.setInterval(atualizar, 400)

    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(atualizar) : null
    if (ro && alvoRef.current) ro.observe(alvoRef.current)

    return () => {
      window.removeEventListener('resize', atualizar)
      window.removeEventListener('scroll', atualizar, true)
      window.removeEventListener('orientationchange', atualizar)
      window.clearInterval(intervalo)
      ro?.disconnect()
    }
    // `rect === null` e não `rect`: só interessa a virada de "ainda não achei"
    // para "achei", que é quando o ResizeObserver tem em quem se pendurar. Com
    // `rect` na lista, cada pixel que o alvo se mexe refaria as inscrições.
  }, [aberto, passo, rect === null])

  /* ── Altura do balão, para caber acima ou abaixo do alvo ──────────────── */
  useLayoutEffect(() => {
    if (!aberto) return
    const h = balaoRef.current?.offsetHeight ?? 0
    if (h && h !== alturaBalao) setAlturaBalao(h)
  })

  /* ── Trava a rolagem do fundo ───────────────────────────────────────────
     Mesma compensação de barra do Modal do sistema: sem ela a página inteira
     dá um pulo lateral no instante em que o tour abre. */
  useEffect(() => {
    if (!aberto) return
    const { body } = document
    const overflowAntes = body.style.overflow
    const padAntes = body.style.paddingRight
    const folga = window.innerWidth - document.documentElement.clientWidth
    body.style.overflow = 'hidden'
    if (folga > 0) body.style.paddingRight = `${folga}px`
    return () => {
      body.style.overflow = overflowAntes
      body.style.paddingRight = padAntes
    }
  }, [aberto])

  /* ── Teclado ────────────────────────────────────────────────────────────
     Esc sai (e sair conta como pular, que é o combinado: não volta sozinho).
     As setas andam no tour, mas só quando o foco não está num campo · a página
     de trás continua montada e alguém pode estar com o cursor dentro dela. */
  const avancar = useCallback(() => {
    if (ultimo) concluir()
    else proximo()
  }, [ultimo, concluir, proximo])

  useEffect(() => {
    if (!aberto) return
    const naTecla = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement | null
      const digitando = !!alvo?.closest('input, textarea, select, [contenteditable="true"]')
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        pular()
        return
      }
      if (digitando) return
      if (e.key === 'ArrowRight') { e.preventDefault(); avancar() }
      if (e.key === 'ArrowLeft')  { e.preventDefault(); voltar() }
    }
    document.addEventListener('keydown', naTecla, true)
    return () => document.removeEventListener('keydown', naTecla, true)
  }, [aberto, pular, avancar, voltar])

  /* ── Foco ───────────────────────────────────────────────────────────────
     Cada passo devolve o foco ao balão, e o Tab circula dentro dele. Sem o
     laço, tabular saía para a página de trás, que está coberta pelo véu: o
     usuário de teclado perdia o cursor num lugar que ele não vê. */
  useEffect(() => {
    if (!aberto) return
    balaoRef.current?.focus({ preventScroll: true })
  }, [aberto, passo])

  useEffect(() => {
    if (!aberto) return
    const seletor = 'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
    const noTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !balaoRef.current) return
      const itens = Array.from(balaoRef.current.querySelectorAll<HTMLElement>(seletor))
        .filter(el => el.offsetParent !== null)
      if (!itens.length) return
      const inicio = itens[0]
      const fim = itens[itens.length - 1]
      const foco = document.activeElement
      if (e.shiftKey && (foco === inicio || foco === balaoRef.current)) {
        e.preventDefault()
        fim.focus()
      } else if (!e.shiftKey && foco === fim) {
        e.preventDefault()
        inicio.focus()
      }
    }
    document.addEventListener('keydown', noTab, true)
    return () => document.removeEventListener('keydown', noTab, true)
  }, [aberto])

  /* `pausado` sai da tela inteirinho: um passo pediu um formulário de verdade
     (o da banca abre o SetupModal, que é z-50) e o tour, em z-80, ficaria por
     cima do formulário que ele mesmo mandou abrir. Os efeitos continuam vivos,
     inclusive a trava de rolagem, então a página de trás não corre embaixo do
     formulário. */
  if (!aberto || pausado || !step) return null

  /* ── Onde o balão fica ─────────────────────────────────────────────────
     Três geometrias, e a regra de todas é a mesma: não cobrir o que o passo
     está apontando. Sem destaque, diálogo centrado (folha no rodapé, no
     celular). Com destaque, cada ramo abaixo explica a sua. */
  const semDestaque = !rect || procurando

  let estilo: React.CSSProperties
  if (semDestaque) {
    estilo = noCelular
      ? { left: MARGEM, right: MARGEM, bottom: MARGEM }
      : {
          left: Math.max(MARGEM, (janela.w - LARGURA_BALAO) / 2),
          top: Math.max(MARGEM, (janela.h - alturaBalao) / 2),
          width: LARGURA_BALAO,
        }
  } else if (noCelular) {
    /*
     * Folha no lado que tem mais espaço, e alta só até onde esse espaço vai.
     *
     * O lado sai da MEDIDA e não de onde o alvo está: com o alvo perto do meio
     * da tela os dois palpites coincidem, mas com um card alto, alinhado pelo
     * topo, "está na metade de cima, então põe a folha embaixo" e "embaixo é
     * onde sobra espaço" divergem, e só o segundo evita cobrir o destaque.
     *
     * Sem o teto de altura, um passo de texto longo ocupava os 82dvh da classe
     * e encostava no elemento que está explicando · exatamente o que a folha
     * existe para não fazer. Passando do teto, o conteúdo rola dentro dela, que
     * é o certo aqui.
     */
    const espacoAcima = rect.top - FOLGA - MARGEM * 2
    const espacoAbaixo = janela.h - (rect.top + rect.height) - FOLGA - MARGEM * 2
    const noTopo = espacoAcima > espacoAbaixo
    const maxHeight = Math.max(noTopo ? espacoAcima : espacoAbaixo, ALTURA_MINIMA)
    estilo = noTopo
      ? { left: MARGEM, right: MARGEM, top: MARGEM, maxHeight }
      : { left: MARGEM, right: MARGEM, bottom: MARGEM, maxHeight }
  } else {
    /*
     * Desktop: abaixo, acima, ao lado, e só então centralizado.
     *
     * O lado não é firula. O botão de apostar fica na base de um card alto, no
     * canto esquerdo da tela: não cabe balão abaixo dele (acaba a janela) nem
     * acima (o card ocupa tudo), e caindo direto no "centralizado" o balão
     * pousava EM CIMA do botão que ele está apontando · o destaque existia e
     * ninguém via. Numa tela larga sobra espaço horizontal de sobra, então a
     * lateral resolve antes de chegar ao último recurso.
     */
    const meioVertical = Math.min(
      Math.max(MARGEM, rect.top + rect.height / 2 - alturaBalao / 2),
      Math.max(MARGEM, janela.h - alturaBalao - MARGEM),
    )
    const centroHorizontal = Math.min(
      Math.max(MARGEM, rect.left + rect.width / 2 - LARGURA_BALAO / 2),
      Math.max(MARGEM, janela.w - LARGURA_BALAO - MARGEM),
    )

    const abaixo = rect.top + rect.height + FOLGA + RESPIRO
    const acima = rect.top - FOLGA - RESPIRO - alturaBalao
    const aDireita = rect.left + rect.width + FOLGA + RESPIRO
    const aEsquerda = rect.left - FOLGA - RESPIRO - LARGURA_BALAO

    if (abaixo + alturaBalao <= janela.h - MARGEM) {
      estilo = { top: abaixo, left: centroHorizontal, width: LARGURA_BALAO }
    } else if (acima >= MARGEM) {
      estilo = { top: acima, left: centroHorizontal, width: LARGURA_BALAO }
    } else if (aDireita + LARGURA_BALAO <= janela.w - MARGEM) {
      estilo = { top: meioVertical, left: aDireita, width: LARGURA_BALAO }
    } else if (aEsquerda >= MARGEM) {
      estilo = { top: meioVertical, left: aEsquerda, width: LARGURA_BALAO }
    } else {
      estilo = {
        top: Math.max(MARGEM, (janela.h - alturaBalao) / 2),
        left: centroHorizontal,
        width: LARGURA_BALAO,
      }
    }
  }

  const Icone = step.Icon
  const pct = Math.round(((passo + 1) / total) * 100)

  return createPortal(
    <div className="fixed inset-0 z-[80]" role="presentation">
      {/* Véu. `onMouseDown` em vez de `onClick` para engolir o clique antes de
          ele virar foco em algo lá atrás. Não fecha o tour: fechar sem querer
          um tour que não volta sozinho é pior do que um clique ignorado. */}
      <div
        className="absolute inset-0"
        onMouseDown={e => { e.preventDefault(); e.stopPropagation() }}
        aria-hidden="true"
      />

      <svg className="absolute inset-0 w-full h-full pointer-events-none" aria-hidden="true">
        <defs>
          <mask id="pickia-tour-furo">
            <rect x="0" y="0" width="100%" height="100%" fill="white" />
            {!semDestaque && (
              <motion.rect
                initial={false}
                animate={{
                  x: rect.left - FOLGA,
                  y: rect.top - FOLGA,
                  width: rect.width + FOLGA * 2,
                  height: rect.height + FOLGA * 2,
                }}
                transition={{ type: 'spring', stiffness: 320, damping: 34 }}
                rx="10"
                fill="black"
              />
            )}
          </mask>
        </defs>
        <rect
          x="0"
          y="0"
          width="100%"
          height="100%"
          fill="rgba(0,0,0,0.74)"
          mask="url(#pickia-tour-furo)"
        />
      </svg>

      {/* Anel do destaque. O furo já separa o elemento pelo brilho; o anel
          existe para quem não distingue essa diferença de luminância, e por
          isso ele é traçado grosso e não só uma cor diferente. */}
      {!semDestaque && (
        <motion.div
          initial={false}
          animate={{
            top: rect.top - FOLGA,
            left: rect.left - FOLGA,
            width: rect.width + FOLGA * 2,
            height: rect.height + FOLGA * 2,
          }}
          transition={{ type: 'spring', stiffness: 320, damping: 34 }}
          className="absolute rounded-lg border-2 border-accent pointer-events-none shadow-[0_0_0_4px_rgba(0,204,0,0.16)]"
          aria-hidden="true"
        />
      )}

      {/*
        Balão.

        `key={step.id}` remonta o balão a cada passo, e é isso que faz a
        entrada (`initial` -> `animate`) tocar de novo em vez de o texto trocar
        seco. Não há AnimatePresence aqui de propósito: com ela, o framer-motion
        clona o filho para orquestrar a saída e passa o `ref` como prop comum,
        o que o React 18 acusa no console ("`ref` is not a prop") · e a animação
        de saída não faria falta, já que o passo seguinte entra na mesma hora.
      */}
        <motion.div
          key={step.id}
          ref={balaoRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="pickia-tour-titulo"
          aria-describedby="pickia-tour-resumo"
          tabIndex={-1}
          initial={{ opacity: 0, y: 10, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          style={estilo}
          className={cn(
            'absolute bg-surface-1 border border-line-strong rounded-lg shadow-elev',
            'flex flex-col overflow-hidden focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/50',
            'max-h-[82dvh]',
          )}
        >
          {/* Barra de progresso. Some do fluxo de leitura porque o número
              logo abaixo diz a mesma coisa em palavras. */}
          <div className="h-1 bg-surface-3 shrink-0" aria-hidden="true">
            <motion.div
              className="h-full bg-accent"
              initial={false}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            />
          </div>

          <div className="flex items-start gap-3 px-4 pt-4 pb-3 shrink-0">
            <div className="w-9 h-9 rounded-md bg-accent/10 border border-accent/25 flex items-center justify-center shrink-0">
              <Icone className="w-4.5 h-4.5 text-accent-ink" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] font-bold text-ink-4 tracking-wide">
                Passo {passo + 1} de {total}
              </p>
              <h2
                id="pickia-tour-titulo"
                className="font-display text-base font-semibold text-ink-1 leading-tight"
              >
                {step.titulo}
              </h2>
            </div>
            <button
              type="button"
              onClick={pular}
              aria-label="Fechar tutorial"
              className="text-ink-4 hover:text-ink-1 transition-colors shrink-0 -mr-1 -mt-0.5 p-1.5 rounded-md"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="px-4 pb-4 space-y-3 overflow-y-auto overscroll-contain">
            <p id="pickia-tour-resumo" className="text-xs text-ink-2 leading-relaxed">
              {step.resumo}
            </p>
            {step.corpo}
            {/* O passo tinha um elemento para destacar e ele não estava na tela.
                Dizer isso é melhor do que deixar o balão centrado sem explicação
                (e melhor ainda do que desenhar um card falso no lugar). */}
            {step.alvos && semDestaque && !procurando && (
              <p className="text-[11px] text-ink-4 leading-relaxed border-l-2 border-line-strong pl-2.5">
                Esta parte da tela ainda não tem nada para mostrar na sua conta, e
                aparece aqui assim que houver conteúdo.
              </p>
            )}
          </div>

          {/* Ações. "Pular tutorial" fica à esquerda, longe do polegar que vai
              e volta entre Voltar e Próximo no celular.

              `flex-wrap` não é decoração: no último passo o botão se chama
              "Começar a usar a PickIA", e numa tela de 390px a fila inteira não
              cabe · sem a quebra, o rótulo saía cortado pela borda do balão. Os
              pontos somem abaixo de `sm` pelo mesmo motivo, e nada se perde: o
              "Passo N de 7" logo acima e a barra de progresso dizem o mesmo. */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 border-t border-line bg-surface-1 shrink-0">
            <button
              type="button"
              onClick={pular}
              className="text-[11px] text-ink-4 hover:text-ink-2 transition-colors px-1 py-2 rounded-md shrink-0"
            >
              Pular tutorial
            </button>

            <div className="hidden sm:flex items-center gap-1.5 mx-auto" aria-hidden="true">
              {passos.map((s, i) => (
                <button
                  key={s.id}
                  type="button"
                  tabIndex={-1}
                  onClick={() => irPara(i)}
                  className={cn(
                    'rounded-full transition-all duration-2 ease-smooth',
                    i === passo ? 'w-4 h-1.5 bg-accent' : 'w-1.5 h-1.5 bg-surface-3 hover:bg-ink-4',
                  )}
                />
              ))}
            </div>

            {/* `ml-auto` mantém as ações à direita também quando elas descem
                para a linha de baixo · `justify-between` do pai só alinha quem
                divide a MESMA linha. */}
            <div className="flex items-center gap-2 shrink-0 ml-auto">
              {!primeiro && (
                <button
                  type="button"
                  onClick={voltar}
                  className="inline-flex items-center gap-1 text-xs font-medium text-ink-2 hover:text-ink-1 border border-line-strong hover:border-ink-4 px-3 py-2 rounded-md transition-colors min-h-[36px]"
                >
                  <ChevronLeft className="w-3.5 h-3.5" aria-hidden="true" />
                  Voltar
                </button>
              )}
              <button
                type="button"
                onClick={avancar}
                className="inline-flex items-center gap-1 text-xs font-bold bg-accent hover:bg-accent-hover active:bg-accent-press text-black px-3.5 py-2 rounded-md transition-colors min-h-[36px]"
              >
                {step.avancar ?? 'Próximo'}
                {!ultimo && !step.avancar && <ChevronRight className="w-3.5 h-3.5" aria-hidden="true" />}
              </button>
            </div>
          </div>
        </motion.div>

      {/* Anúncio para leitor de tela. O balão troca de conteúdo sem trocar de
          elemento, então sem esta região a mudança de passo passa em silêncio. */}
      <p className="sr-only" role="status" aria-live="polite">
        Passo {passo + 1} de {total}: {step.titulo}. {step.resumo}
      </p>
    </div>,
    document.body,
  )
}
