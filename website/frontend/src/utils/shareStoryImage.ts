import { getResultStyle, PICK_TYPE_LABEL, PICK_TYPE_HEX } from './resultStyle'

const W = 1080
const H = 1920

export interface StoryImageInput {
  homeTeamName: string
  awayTeamName?: string
  homeTeamId?: number
  awayTeamId?: number
  leagueName?: string
  pickType: string
  market?: string
  line?: string
  odd: number
  result?: string | null
  profit?: number | null
  shareUrl: string
  /** Win rate geral do site (0-100), pra prova social no card. Omitir se indisponível. */
  winRatePct?: number | null
  /**
   * Probabilidade estimada DESTE pick (0-100).
   *
   * Tem prioridade sobre `winRatePct` no terceiro ladrilho. O card mostrava
   * "ACERTO 30D", que e' o acerto do SITE nos ultimos 30 dias -- numero de
   * outro assunto, colado em cima de odd e lucro que sao deste pick. Quem le
   * junta os tres e entende que 67% era a chance daquela aposta. Probabilidade
   * do proprio pick responde a pergunta que o leitor ja estava fazendo.
   */
  probabilityPct?: number | null
}

// ── Tipografia ───────────────────────────────────────────────────────────
// As mesmas duas famílias do site (index.css / tailwind.config): Space
// Nunito no display, Inter nos números. Antes tudo era system-ui,
// então a imagem compartilhada não parecia do mesmo produto que a página.
//
// Canvas não espera webfont carregar: se desenhar antes, cai no fallback
// silenciosamente e o resultado varia por dispositivo. ensureFonts() força o
// carregamento uma vez e é aguardado por todos os builders.
const DISPLAY = 'Nunito, -apple-system, BlinkMacSystemFont, sans-serif'
const MONO = 'Inter, -apple-system, BlinkMacSystemFont, sans-serif'
const SANS = 'Nunito, -apple-system, BlinkMacSystemFont, sans-serif'

// Pedir um peso que a família não carrega faz o navegador SIMULAR o negrito
// (faux bold), e o traço sintetizado muda de aparelho pra aparelho: a mesma
// pick sairia com espessura diferente em dois celulares. Por isso cada teto
// abaixo espelha o que index.html realmente baixa.
//
// Nunito: 400..800.  Inter (numeros): 400..700.
const clamp800 = (peso: number) => Math.min(peso, 800)
const clamp700 = (peso: number) => Math.min(peso, 700)

const fontDisplay = (peso: number, tam: number) => `${clamp800(peso)} ${tam}px ${DISPLAY}`
const fontMono = (peso: number, tam: number) => `${clamp700(peso)} ${tam}px ${MONO}`
const fontSans = (peso: number, tam: number) => `${clamp800(peso)} ${tam}px ${SANS}`

let fontesPromise: Promise<void> | null = null
function ensureFonts(): Promise<void> {
  if (fontesPromise) return fontesPromise
  const fonts = (document as any).fonts
  if (!fonts?.load) return (fontesPromise = Promise.resolve())
  fontesPromise = Promise.all([
    fonts.load('800 58px Nunito'),
    fonts.load('600 28px Nunito'),
    fonts.load('700 52px Inter'),
    fonts.load('500 24px Inter'),
    fonts.load('800 40px Nunito'),
    fonts.load('700 26px Nunito'),
  ])
    .then(() => undefined)
    // Falha de rede na fonte não pode impedir o compartilhamento: cai no
    // fallback da própria stack CSS e segue.
    .catch(() => undefined)
  return fontesPromise
}

/**
 * Fundo dos cards · chapado, como nos carrosséis do Instagram.
 *
 * Já foi degradê + grade + dois glows diagonais + vinheta, cinco camadas
 * empilhadas atrás de tudo. A intenção era dar movimento, mas o efeito somado
 * foi uma lavagem esverdeada em cima da imagem inteira: o escudo dos times
 * boiava num borrão e o card não parecia do mesmo produto que os carrosséis.
 *
 * Cor de destaque rende mais concentrada num elemento sólido do que diluída no
 * fundo todo. A paleta é a mesma de scripts/video/cartoes.py.
 */
function drawBackground(ctx: CanvasRenderingContext2D, accentHex: string): void {
  // Fundo CHAPADO, mesmo #0a0a0c dos carrosseis (scripts/video/cartoes.py).
  //
  // A versao anterior empilhava cinco camadas: degrade de base tingido de
  // verde, grade de linhas, dois glows radiais e uma vinheta. Cada uma sozinha
  // era sutil; somadas viravam uma lavagem esverdeada que sujava o card
  // inteiro e deixava o escudo dos times boiando num borrao. Cor de destaque
  // rende mais em UM elemento solido do que espalhada pelo fundo todo.
  ctx.fillStyle = '#0a0a0c'
  ctx.fillRect(0, 0, W, H)

  // Um unico brilho, curto e no topo, so' pra tirar a chapa morta.
  const brilho = ctx.createRadialGradient(W / 2, -H * 0.1, 40, W / 2, -H * 0.1, W * 0.9)
  brilho.addColorStop(0, `${accentHex}26`)
  brilho.addColorStop(1, 'transparent')
  ctx.fillStyle = brilho
  ctx.fillRect(0, 0, W, H * 0.55)
}

/** Faixa fina de destaque no topo, com degradê que some nas pontas. */
function drawTopAccent(ctx: CanvasRenderingContext2D, accentHex: string): void {
  const barra = ctx.createLinearGradient(0, 0, W, 0)
  barra.addColorStop(0, 'transparent')
  barra.addColorStop(0.5, accentHex)
  barra.addColorStop(1, 'transparent')
  ctx.fillStyle = barra
  ctx.fillRect(0, 0, W, 6)
}

/** Texto com brilho na própria cor -- usado nos números que são o destaque. */
function withGlow(ctx: CanvasRenderingContext2D, cor: string, blur: number, fn: () => void): void {
  ctx.save()
  ctx.shadowColor = cor
  ctx.shadowBlur = blur
  fn()
  ctx.restore()
}

function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise(resolve => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => resolve(null)
    img.src = src
  })
}

function drawRoundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

function fitText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text
  let t = text
  while (t.length > 1 && ctx.measureText(t + '…').width > maxWidth) t = t.slice(0, -1)
  return t + '…'
}

/**
 * Círculo do escudo/logo. Quando a imagem falha (proxy fora do ar, time sem
 * escudo mapeado) SEMPRE desenha o círculo base + borda -- antes retornava
 * cedo e não desenhava nada, deixando um buraco no layout (times/ligas sem
 * imagem ficavam com espaço em branco no meio do card).
 */
function drawCircularLogo(ctx: CanvasRenderingContext2D, img: HTMLImageElement | null, cx: number, cy: number, size: number) {
  const r = size / 2
  ctx.save()
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.closePath()
  // Sem disco atras: escudo de time e' PNG com transparencia, e o
  // preenchimento #18181b aparecia como uma bolha preta em volta dele. O aro
  // fica so' pro caso da imagem nao carregar, onde ele e' o proprio marcador.
  if (img) {
    ctx.clip()
    ctx.drawImage(img, cx - r, cy - r, size, size)
  } else {
    ctx.strokeStyle = 'rgba(255,255,255,0.14)'
    ctx.lineWidth = 2
    ctx.stroke()
  }
  ctx.restore()
}

export async function buildStoryImage(input: StoryImageInput): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D não suportado')

  const rs = getResultStyle(input.result)
  // Pick ainda sem resultado usa a cor do TIPO (VIP amarelo, faltas roxo...)
  // em vez do verde genérico -- assim o card já comunica a categoria de longe.
  const typeHexBase = PICK_TYPE_HEX[input.pickType] ?? '#00CC00'
  const accentHex = rs?.hex ?? typeHexBase

  await ensureFonts()
  drawBackground(ctx, accentHex)
  drawTopAccent(ctx, accentHex)

  // Logo
  const logoImg = await loadImage('/logo.png')

  // Mirror dos incrementos de cursorY usados abaixo (876 = soma dos fixos;
  // leagueName/market são as duas únicas seções opcionais que mudam a altura).
  const contentBottomUnshifted = (logoImg ? 290 : 170) + 876
    + (input.leagueName ? 58 : 0) + (input.market ? 80 : 0) + FOOTER_HEIGHT
  ctx.save()
  ctx.translate(0, computeShiftY(contentBottomUnshifted))

  if (logoImg) {
    ctx.drawImage(logoImg, W / 2 - 70, 100, 140, 140)
  }
  const brandY = logoImg ? 290 : 170
  ctx.font = fontDisplay(900, 58)
  const pickW = ctx.measureText('Pick').width
  const iaW = ctx.measureText('IA').width
  ctx.textAlign = 'left'
  ctx.fillStyle = '#ffffff'
  ctx.fillText('Pick', W / 2 - (pickW + iaW) / 2, brandY)
  ctx.fillStyle = '#00CC00'
  ctx.fillText('IA', W / 2 - (pickW + iaW) / 2 + pickW, brandY)

  // Badge do tipo de pick
  ctx.textAlign = 'center'
  const typeLabel = PICK_TYPE_LABEL[input.pickType] ?? 'VIP'
  const typeHex = PICK_TYPE_HEX[input.pickType] ?? '#facc15'
  ctx.font = fontDisplay(800, 30)
  const badgeTextW = ctx.measureText(typeLabel.toUpperCase()).width
  const badgeW = badgeTextW + 80
  const badgeY = brandY + 56
  drawRoundedRect(ctx, W / 2 - badgeW / 2, badgeY, badgeW, 64, 32)
  ctx.fillStyle = `${typeHex}22`
  ctx.fill()
  ctx.strokeStyle = `${typeHex}66`
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.fillStyle = typeHex
  ctx.fillText(typeLabel.toUpperCase(), W / 2, badgeY + 43)

  let cursorY = badgeY + 64

  if (input.leagueName) {
    cursorY += 58
    ctx.font = fontSans(600, 28)
    ctx.fillStyle = '#71717a'
    ctx.fillText(fitText(ctx, input.leagueName, W - 160), W / 2, cursorY)
  }

  // Times
  cursorY += 160
  const [homeLogo, awayLogo] = await Promise.all([
    input.homeTeamId ? loadImage(`/api/proxy/team/${input.homeTeamId}.png`) : Promise.resolve(null),
    input.awayTeamId ? loadImage(`/api/proxy/team/${input.awayTeamId}.png`) : Promise.resolve(null),
  ])

  const logoSize = 116
  drawCircularLogo(ctx, homeLogo, W / 2 - 260, cursorY, logoSize)
  drawCircularLogo(ctx, awayLogo, W / 2 + 260, cursorY, logoSize)

  ctx.font = fontDisplay(900, 46)
  ctx.fillStyle = '#ffffff'
  ctx.fillText(fitText(ctx, input.homeTeamName, 340), W / 2, cursorY - 88)
  ctx.font = fontSans(700, 30)
  ctx.fillStyle = '#52525b'
  ctx.fillText('vs', W / 2, cursorY + 14)
  if (input.awayTeamName) {
    ctx.font = fontDisplay(900, 46)
    ctx.fillStyle = '#ffffff'
    ctx.fillText(fitText(ctx, input.awayTeamName, 340), W / 2, cursorY + 110)
  }

  cursorY += 190

  if (input.market) {
    const marketText = input.line ? `${input.market}, ${input.line}` : input.market
    ctx.font = fontDisplay(800, 36)
    const fitted = fitText(ctx, marketText, W - 240)
    const textW = ctx.measureText(fitted).width
    const boxW = Math.min(textW + 80, W - 120)
    const boxH = 76
    const boxY = cursorY - 52
    drawRoundedRect(ctx, W / 2 - boxW / 2, boxY, boxW, boxH, 22)
    ctx.fillStyle = 'rgba(255,255,255,0.07)'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.18)'
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.fillStyle = '#ffffff'
    ctx.fillText(fitted, W / 2, boxY + 51)
    cursorY += 80
  }

  // Selo de resultado
  cursorY += 44
  const resultLabel = rs ? rs.label : 'A CONFIRMAR'
  ctx.font = fontDisplay(900, 72)
  const resultTextW = ctx.measureText(resultLabel).width
  const resultBoxW = resultTextW + 120
  // Preenchimento em degradê + brilho na borda: o selo é o elemento que
  // decide se alguém para de rolar o feed, então é onde vale o peso visual.
  const seloGrad = ctx.createLinearGradient(0, cursorY, 0, cursorY + 122)
  seloGrad.addColorStop(0, `${accentHex}33`)
  seloGrad.addColorStop(1, `${accentHex}14`)
  drawRoundedRect(ctx, W / 2 - resultBoxW / 2, cursorY, resultBoxW, 122, 26)
  ctx.fillStyle = seloGrad
  ctx.fill()
  withGlow(ctx, `${accentHex}aa`, 26, () => {
    ctx.strokeStyle = accentHex
    ctx.lineWidth = 3
    ctx.stroke()
  })
  withGlow(ctx, `${accentHex}88`, 24, () => {
    ctx.fillStyle = accentHex
    ctx.fillText(resultLabel, W / 2, cursorY + 88)
  })
  cursorY += 122

  // Estatísticas: odd, lucro e a chance estimada deste pick.
  cursorY += 90
  const prob = input.probabilityPct ?? null
  const hasWinRate = prob == null && input.winRatePct != null
  const profitText = input.profit != null
    ? `${input.profit >= 0 ? '+' : ''}${input.profit.toFixed(2)}u`
    : `+${(input.odd - 1).toFixed(2)}u`
  const profitColor = input.profit != null ? (input.profit >= 0 ? '#4ade80' : '#f87171') : '#a1a1aa'

  const stats = [
    { label: 'ODD', value: input.odd.toFixed(2), color: '#4ade80' },
    { label: input.profit != null ? 'LUCRO' : 'LUCRO POT.', value: profitText, color: profitColor },
    // Prioridade pra probabilidade DO PICK · "ACERTO 30D" fica so' de reserva,
    // pra quando o pick nao carrega probabilidade, e com rotulo que diz de
    // quem e o numero.
    ...(prob != null
      ? [{ label: 'CHANCE', value: `${Math.round(prob)}%`, color: '#facc15' }]
      : hasWinRate
        ? [{ label: 'ACERTO DO SITE', value: `${Math.round(input.winRatePct!)}%`, color: '#facc15' }]
        : []),
  ]
  const totalW = W - 200
  const colW = totalW / stats.length
  const statsX = W / 2 - totalW / 2
  stats.forEach((s, i) => {
    const cx = statsX + colW * i + colW / 2
    // Divisória fina entre as colunas: separa os números sem precisar de
    // caixa em volta de cada um.
    if (i > 0) {
      ctx.fillStyle = 'rgba(255,255,255,0.10)'
      ctx.fillRect(statsX + colW * i, cursorY - 26, 1, 92)
    }
    ctx.font = fontMono(700, 24)
    ctx.fillStyle = '#71717a'
    ctx.fillText(s.label, cx, cursorY)
    ctx.font = fontMono(900, 52)
    withGlow(ctx, `${s.color}66`, 18, () => {
      ctx.fillStyle = s.color
      ctx.fillText(s.value, cx, cursorY + 58)
    })
  })

  cursorY += 150

  // ── Oferta + link (compacto · sem QR: quem vê o Story está no mesmo
  //    celular, então não dá pra escanear; um link grande e memorável
  //    funciona melhor, e deixa espaço livre pra pessoa colar o sticker
  //    de link do Instagram por cima) ─────────────────────────────────
  drawCtaFooter(ctx, cursorY, input.shareUrl)
  ctx.restore()
  drawFooterCredit(ctx)

  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error('Falha ao gerar imagem'))
    }, 'image/png', 0.95)
  })
}

// ── Centralização vertical ───────────────────────────────────────────────
// Os cards são desenhados de cima pra baixo e paravam onde o conteúdo
// acabava, deixando 35-40% do canvas (formato Story, 1080x1920) vazio embaixo
// -- achado real comparando as 4 variações renderizadas. FOOTER_HEIGHT é a
// altura fixa do bloco final (pill + instrução "Acesse agora:" + botão de
// domínio) desenhado por drawCtaFooter/buildStoryImage; CREDIT_Y é onde a
// linha de crédito no rodapé fica ancorada (sempre no mesmo lugar, não
// desloca). computeShiftY calcula quanto dá pra empurrar o conteúdo pra
// baixo (metade do espaço sobrando, com teto) sem chegar perto da linha de
// crédito -- cards com pouco conteúdo (ex: resultado geral) ganham mais
// respiro; cards com muita linha (ex: 8 jogos de hoje) já preenchem o
// quadro e não são deslocados.
const FOOTER_HEIGHT = 58 + 48 + 48 + 112
const CREDIT_Y = H - 60
function computeShiftY(contentBottomUnshifted: number): number {
  const slack = Math.max(0, (CREDIT_Y - 100) - contentBottomUnshifted)
  return Math.min(slack * 0.4, 240)
}

function drawFooterCredit(ctx: CanvasRenderingContext2D): void {
  ctx.font = fontSans(600, 23)
  ctx.fillStyle = '#3f3f46'
  ctx.textAlign = 'center'
  ctx.fillText('Pick IA. Tips por Inteligência Artificial', W / 2, CREDIT_Y)
}

// ── Helpers compartilhados pelos cards abaixo (resultado geral / jogos do dia) ──
function drawBrandHeader(ctx: CanvasRenderingContext2D, logoImg: HTMLImageElement | null): number {
  if (logoImg) {
    ctx.drawImage(logoImg, W / 2 - 70, 100, 140, 140)
  }
  const brandY = logoImg ? 290 : 170
  ctx.font = fontDisplay(900, 58)
  const pickW = ctx.measureText('Pick').width
  const iaW = ctx.measureText('IA').width
  ctx.textAlign = 'left'
  ctx.fillStyle = '#ffffff'
  ctx.fillText('Pick', W / 2 - (pickW + iaW) / 2, brandY)
  ctx.fillStyle = '#00CC00'
  ctx.fillText('IA', W / 2 - (pickW + iaW) / 2 + pickW, brandY)
  ctx.textAlign = 'center'
  return brandY
}

function drawCtaFooter(ctx: CanvasRenderingContext2D, cursorY: number, shareUrl: string): void {
  const pillLabel = '2 DIAS DE VIP GRÁTIS'
  ctx.font = fontDisplay(800, 28)
  const pillW = ctx.measureText(pillLabel).width + 64
  drawRoundedRect(ctx, W / 2 - pillW / 2, cursorY, pillW, 58, 29)
  ctx.fillStyle = '#00CC00'
  ctx.fill()
  ctx.fillStyle = '#04140a'
  ctx.fillText(pillLabel, W / 2, cursorY + 39)
  cursorY += 58 + 48

  // Instrução curta acima do link -- sem isso, quem vê o card fora do
  // Instagram (TikTok, print repostado, sem sticker de link clicável) não
  // sabe que precisa digitar o endereço no navegador.
  ctx.font = fontSans(700, 26)
  ctx.fillStyle = '#a1a1aa'
  ctx.fillText('Acesse agora:', W / 2, cursorY)
  cursorY += 48

  const displayDomain = (() => {
    try { return new URL(shareUrl).hostname.replace(/^www\./, '') }
    catch { return shareUrl.replace(/^https?:\/\//, '').split('/')[0] }
  })()
  const linkText = fitText(ctx, displayDomain, W - 320)
  ctx.font = fontDisplay(900, 48)
  const linkTextW = ctx.measureText(linkText).width
  const btnPadX = 56
  const btnW = linkTextW + btnPadX * 2
  const btnH = 112
  drawRoundedRect(ctx, W / 2 - btnW / 2, cursorY, btnW, btnH, btnH / 2)
  ctx.fillStyle = 'rgba(255,255,255,0.06)'
  ctx.fill()
  ctx.strokeStyle = '#ffffff'
  ctx.lineWidth = 2.5
  ctx.stroke()

  ctx.textAlign = 'left'
  const textX = W / 2 - btnW / 2 + btnPadX
  const textY = cursorY + btnH / 2 + 17
  ctx.fillStyle = '#ffffff'
  ctx.fillText(linkText, textX, textY)
  ctx.textAlign = 'center'
}

function toBlobPromise(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error('Falha ao gerar imagem'))
    }, 'image/png', 0.95)
  })
}

// ── Card: resultado geral da IA (win rate, picks, lucro) ────────────────────
export interface ResultsStoryInput {
  winRatePct: number
  total: number
  greens: number
  reds: number
  profit: number
  shareUrl: string
  /** Texto do badge no topo. Default: "RESULTADOS DA IA" */
  badgeLabel?: string
  /** Texto de rodapé acima do CTA. Default: "Histórico 100% auditável e público" */
  footerText?: string
}

export async function buildResultsStoryImage(input: ResultsStoryInput): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D não suportado')

  const accentHex = '#00CC00'

  await ensureFonts()
  drawBackground(ctx, accentHex)
  drawTopAccent(ctx, accentHex)
  const topBar = ctx.createLinearGradient(0, 0, W, 0)
  topBar.addColorStop(0, 'transparent')
  topBar.addColorStop(0.5, accentHex)
  topBar.addColorStop(1, 'transparent')
  ctx.fillStyle = topBar
  ctx.fillRect(0, 0, W, 6)

  const logoImg = await loadImage('/logo.png')

  // Altura do conteúdo é fixa nesse card (não depende de nenhum dado
  // variável de input) -- mirror dos incrementos de cursorY usados abaixo.
  const contentBottomUnshifted = (logoImg ? 290 : 170) + 56 + 64 + 180 + 150 + 220 + 90 + FOOTER_HEIGHT
  ctx.save()
  ctx.translate(0, computeShiftY(contentBottomUnshifted))

  const brandY = drawBrandHeader(ctx, logoImg)

  let cursorY = brandY + 56
  ctx.font = fontDisplay(800, 30)
  const badgeLabel = input.badgeLabel ?? 'RESULTADOS DA IA'
  const badgeTextW = ctx.measureText(badgeLabel).width
  const badgeW = badgeTextW + 80
  drawRoundedRect(ctx, W / 2 - badgeW / 2, cursorY, badgeW, 64, 32)
  ctx.fillStyle = `${accentHex}22`
  ctx.fill()
  ctx.strokeStyle = `${accentHex}88`
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.fillStyle = accentHex
  ctx.fillText(badgeLabel, W / 2, cursorY + 43)
  cursorY += 64

  // Win rate em destaque -- verde-400 (#4ade80), o mesmo tom usado em TODO
  // resultado positivo no site de verdade (text-green-400: badges GREEN,
  // stat boxes de greens em Landing/Results/ResultadosPublicos). accentHex
  // (#00CC00/green-500) e' a cor da marca (botao/logo/CTA), usada so no
  // "chrome" do card (badge, glow, barra do topo, rodape) -- sao duas
  // cores intencionalmente diferentes no design system (ver tailwind.config),
  // nao um erro; misturar as duas pro mesmo elemento que antes era so
  // uma delas e' o que ficava com o verde "diferente de antes".
  const resultGreen = '#4ade80'
  cursorY += 180
  ctx.font = fontMono(900, 220)
  ctx.shadowColor = `${resultGreen}99`
  ctx.shadowBlur = 40
  ctx.fillStyle = resultGreen
  ctx.fillText(`${Math.round(input.winRatePct)}%`, W / 2, cursorY)
  ctx.shadowBlur = 0
  ctx.font = fontSans(700, 34)
  ctx.fillStyle = '#a1a1aa'
  ctx.fillText('WIN RATE', W / 2, cursorY + 54)

  // Estatísticas: total, greens, lucro
  cursorY += 150
  const profitText = `${input.profit >= 0 ? '+' : ''}${input.profit.toFixed(1)}u`
  const stats = [
    { label: 'PICKS', value: String(input.total), color: '#ffffff' },
    { label: 'GREENS', value: String(input.greens), color: resultGreen },
    { label: 'LUCRO', value: profitText, color: input.profit >= 0 ? resultGreen : '#f87171' },
  ]
  const totalW = W - 200
  const colW = totalW / stats.length
  const statsX = W / 2 - totalW / 2
  stats.forEach((s, i) => {
    const cx = statsX + colW * i + colW / 2
    ctx.font = fontSans(700, 26)
    ctx.fillStyle = '#71717a'
    ctx.fillText(s.label, cx, cursorY)
    ctx.font = fontDisplay(900, 58)
    ctx.fillStyle = s.color
    ctx.fillText(s.value, cx, cursorY + 64)
  })

  cursorY += 220
  ctx.font = fontSans(600, 28)
  ctx.fillStyle = '#52525b'
  ctx.fillText(input.footerText ?? 'Histórico 100% auditável e público', W / 2, cursorY)

  cursorY += 90
  drawCtaFooter(ctx, cursorY, input.shareUrl)
  ctx.restore()
  drawFooterCredit(ctx)

  return toBlobPromise(canvas)
}

// ── Card: jogos de hoje que a IA vai analisar ───────────────────────────────
export interface TodayGameItem {
  homeTeamName: string
  awayTeamName: string
  homeTeamId?: number | null
  awayTeamId?: number | null
  leagueName?: string
}

export interface TodayGamesStoryInput {
  games: TodayGameItem[]
  shareUrl: string
  /** 'hoje' (picks já saíram, IA já analisou) ou 'amanha' (prévia, picks saem só amanhã de manhã). Default: 'hoje'. */
  variant?: 'hoje' | 'amanha'
}

export async function buildTodayGamesStoryImage(input: TodayGamesStoryInput): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D não suportado')

  const accentHex = '#facc15'

  await ensureFonts()
  drawBackground(ctx, accentHex)
  drawTopAccent(ctx, accentHex)

  const logoImg = await loadImage('/logo.png')
  const games = input.games.slice(0, 8)
  const rowH = games.length > 6 ? 128 : 154
  const logoSize = games.length > 6 ? 44 : 52

  // Mirror dos incrementos de cursorY usados abaixo (só a lista de jogos
  // varia de tamanho -- o resto do card é fixo).
  const contentBottomUnshifted = (logoImg ? 290 : 170) + 56 + 60 + 70 + games.length * rowH + 60 + FOOTER_HEIGHT
  ctx.save()
  ctx.translate(0, computeShiftY(contentBottomUnshifted))

  const brandY = drawBrandHeader(ctx, logoImg)

  let cursorY = brandY + 56
  ctx.font = fontDisplay(800, 28)
  const badgeLabel = input.variant === 'amanha'
    ? 'JOGOS DE AMANHÃ. A IA VAI ANALISAR'
    : 'JOGOS DE HOJE. A IA JÁ ANALISOU'
  const badgeTextW = ctx.measureText(badgeLabel).width
  const badgeW = badgeTextW + 72
  drawRoundedRect(ctx, W / 2 - badgeW / 2, cursorY, badgeW, 60, 30)
  ctx.fillStyle = `${accentHex}22`
  ctx.fill()
  ctx.strokeStyle = `${accentHex}66`
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.fillStyle = accentHex
  ctx.fillText(badgeLabel, W / 2, cursorY + 40)
  cursorY += 60 + 70

  const gameLogos = await Promise.all(
    games.map(g => Promise.all([
      g.homeTeamId ? loadImage(`/api/proxy/team/${g.homeTeamId}.png`) : Promise.resolve(null),
      g.awayTeamId ? loadImage(`/api/proxy/team/${g.awayTeamId}.png`) : Promise.resolve(null),
    ]))
  )

  games.forEach((g, i) => {
    const rowY = cursorY + i * rowH
    const [homeLogo, awayLogo] = gameLogos[i]

    drawRoundedRect(ctx, 70, rowY, W - 140, rowH - 16, 20)
    ctx.fillStyle = 'rgba(255,255,255,0.03)'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.07)'
    ctx.lineWidth = 1.5
    ctx.stroke()

    const boxHalf = (rowH - 16) / 2
    const midY = rowY + boxHalf
    drawCircularLogo(ctx, homeLogo, 70 + 70, midY, logoSize)
    drawCircularLogo(ctx, awayLogo, W - 70 - 70, midY, logoSize)

    // Posições proporcionais à altura real da caixa (não fixas) -- com
    // valores fixos, o nome da liga estourava pra fora da caixa (achado
    // real comparando com >6 jogos no card, onde a caixa é mais baixa).
    const nameFont   = games.length > 6 ? '800 26px' : '800 30px'
    const vsFont     = games.length > 6 ? '600 20px' : '600 24px'
    const leagueFont = games.length > 6 ? '600 17px' : '600 20px'

    ctx.textAlign = 'center'
    ctx.font = `${nameFont} ${DISPLAY}`
    ctx.fillStyle = '#ffffff'
    ctx.fillText(fitText(ctx, g.homeTeamName, 300), W / 2, midY - boxHalf * 0.62)
    ctx.font = `${vsFont} ${SANS}`
    ctx.fillStyle = '#52525b'
    ctx.fillText('vs', W / 2, midY - boxHalf * 0.04)
    ctx.font = `${nameFont} ${DISPLAY}`
    ctx.fillStyle = '#ffffff'
    ctx.fillText(fitText(ctx, g.awayTeamName, 300), W / 2, midY + boxHalf * 0.5)

    if (g.leagueName) {
      ctx.font = `${leagueFont} ${SANS}`
      ctx.fillStyle = '#71717a'
      ctx.fillText(fitText(ctx, g.leagueName, 260), W / 2, midY + boxHalf * 0.86)
    }
  })

  cursorY += games.length * rowH + 60
  drawCtaFooter(ctx, cursorY, input.shareUrl)
  ctx.restore()
  drawFooterCredit(ctx)

  return toBlobPromise(canvas)
}

// ── Card: resultados por liga ───────────────────────────────────────────────
export interface LeagueResultItem {
  leagueId?: number | null
  leagueName: string
  total: number
  winRatePct: number
  profit: number
}

export interface LeagueResultsStoryInput {
  leagues: LeagueResultItem[]
  shareUrl: string
  /** Texto do badge no topo. Default: "RESULTADOS POR LIGA" */
  badgeLabel?: string
}

export async function buildLeagueResultsStoryImage(input: LeagueResultsStoryInput): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D não suportado')

  const accentHex = '#00CC00'
  const resultGreen = '#4ade80'

  await ensureFonts()
  drawBackground(ctx, accentHex)

  const topBar = ctx.createLinearGradient(0, 0, W, 0)
  topBar.addColorStop(0, 'transparent')
  topBar.addColorStop(0.5, accentHex)
  topBar.addColorStop(1, 'transparent')
  ctx.fillStyle = topBar
  ctx.fillRect(0, 0, W, 6)

  const logoImg = await loadImage('/logo.png')
  const leagues = input.leagues.slice(0, 6)
  const rowH = leagues.length > 5 ? 108 : 128
  const logoSize = 60

  // Mirror dos incrementos de cursorY usados abaixo.
  const contentBottomUnshifted = (logoImg ? 290 : 170) + 56 + 60 + 66 + leagues.length * rowH + 60 + FOOTER_HEIGHT
  ctx.save()
  ctx.translate(0, computeShiftY(contentBottomUnshifted))

  const brandY = drawBrandHeader(ctx, logoImg)

  let cursorY = brandY + 56
  ctx.font = fontDisplay(800, 28)
  const badgeLabel = input.badgeLabel ?? 'RESULTADOS POR LIGA'
  const badgeTextW = ctx.measureText(badgeLabel).width
  const badgeW = badgeTextW + 72
  drawRoundedRect(ctx, W / 2 - badgeW / 2, cursorY, badgeW, 60, 30)
  ctx.fillStyle = `${accentHex}22`
  ctx.fill()
  ctx.strokeStyle = `${accentHex}88`
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.fillStyle = accentHex
  ctx.fillText(badgeLabel, W / 2, cursorY + 40)
  cursorY += 60 + 66

  const logos = await Promise.all(
    leagues.map(lg => lg.leagueId != null ? loadImage(`/api/proxy/league/${lg.leagueId}.png`) : Promise.resolve(null))
  )

  leagues.forEach((lg, i) => {
    const rowY = cursorY + i * rowH
    const rowInnerH = rowH - 16

    drawRoundedRect(ctx, 70, rowY, W - 140, rowInnerH, 20)
    ctx.fillStyle = 'rgba(255,255,255,0.03)'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.07)'
    ctx.lineWidth = 1.5
    ctx.stroke()

    const midY = rowY + rowInnerH / 2
    drawCircularLogo(ctx, logos[i], 70 + 66, midY, logoSize)

    ctx.textAlign = 'left'
    ctx.font = fontDisplay(800, 32)
    ctx.fillStyle = '#ffffff'
    ctx.fillText(fitText(ctx, lg.leagueName, 420), 70 + 66 + logoSize / 2 + 30, midY - 8)
    ctx.font = fontSans(600, 22)
    ctx.fillStyle = '#71717a'
    ctx.fillText(`${lg.total} picks`, 70 + 66 + logoSize / 2 + 30, midY + 26)

    ctx.textAlign = 'right'
    ctx.font = fontDisplay(900, 40)
    ctx.fillStyle = lg.winRatePct >= 55 ? resultGreen : '#ffffff'
    ctx.fillText(`${Math.round(lg.winRatePct)}%`, W - 70 - 40, midY - 8)
    ctx.font = fontMono(700, 24)
    ctx.fillStyle = lg.profit >= 0 ? resultGreen : '#f87171'
    ctx.fillText(`${lg.profit >= 0 ? '+' : ''}${lg.profit.toFixed(1)}u`, W - 70 - 40, midY + 26)
    ctx.textAlign = 'center'
  })

  cursorY += leagues.length * rowH + 60
  drawCtaFooter(ctx, cursorY, input.shareUrl)
  ctx.restore()
  drawFooterCredit(ctx)

  return toBlobPromise(canvas)
}

// ── Card: alavancagem ───────────────────────────────────────────────────────
export interface AlavancagemLeg {
  homeTeamName: string
  awayTeamName?: string
  homeTeamId?: number | null
  awayTeamId?: number | null
  market?: string
  line?: string
  odd?: number
}

export interface AlavancagemStoryInput {
  legs: AlavancagemLeg[]
  /** "Simples", "Dupla", "Tripla", "Combinada" · como a tela chama. */
  tipoLabel: string
  oddCombined: number
  result?: string | null
  shareUrl: string
  /** Degrau deste pick dentro do caminho, quando se sabe. */
  degrau?: number | null
  /** Greens que fecham o caminho (ALAV_META_PADRAO no backend). */
  meta?: number | null
}

/**
 * Alavancagem não cabe no card de pick comum.
 *
 * O card genérico foi feito pra UM jogo: ele desenha dois escudos, um mercado
 * e uma odd. Uma tripla compartilhada por ali saía anunciando só a PRIMEIRA
 * perna, com a odd combinada de três jogos ao lado dela · quem lia via uma
 * aposta simples pagando 3,20 e nem sabia que existiam outros dois jogos.
 *
 * Aqui as pernas são a informação principal (uma linha cada, com mercado e
 * odd própria), e o composto aparece pelo que ele é: quanto 1 unidade vira se
 * as três entrarem. Quando o degrau do caminho é conhecido, o card também diz
 * em que ponto da escada este pick está · é a pergunta que o produto responde
 * e que nenhum outro tipo de pick tem.
 */
export async function buildAlavancagemStoryImage(input: AlavancagemStoryInput): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D não suportado')

  const rs = getResultStyle(input.result)
  const accentHex = rs?.hex ?? PICK_TYPE_HEX['alavancagem'] ?? '#fb923c'
  const legs = input.legs.slice(0, 3)
  const temMeta = input.degrau != null && input.meta != null && input.meta > 0

  await ensureFonts()
  drawBackground(ctx, accentHex)
  drawTopAccent(ctx, accentHex)

  const logoImg = await loadImage('/logo.png')
  // Altura da linha cai quando há três pernas: com 190px cada, três caixas
  // mais o composto e o selo passavam do rodapé.
  const rowH = legs.length >= 3 ? 168 : 196
  const alturaConteudo = (logoImg ? 290 : 170) + 130 + (temMeta ? 118 : 0)
    + legs.length * rowH + 96 + 122 + 150 + FOOTER_HEIGHT

  ctx.save()
  ctx.translate(0, computeShiftY(alturaConteudo))

  const brandY = drawBrandHeader(ctx, logoImg)
  let cursorY = brandY + 56

  // Badge: ALAVANCAGEM · TRIPLA
  const badgeLabel = `ALAVANCAGEM, ${input.tipoLabel.toUpperCase()}`
  ctx.font = fontDisplay(800, 30)
  const badgeW = ctx.measureText(badgeLabel).width + 80
  drawRoundedRect(ctx, W / 2 - badgeW / 2, cursorY, badgeW, 64, 32)
  ctx.fillStyle = `${accentHex}22`
  ctx.fill()
  ctx.strokeStyle = `${accentHex}66`
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.fillStyle = accentHex
  ctx.fillText(badgeLabel, W / 2, cursorY + 43)
  cursorY += 64 + 66

  // Escada até a meta · segmentos discretos, iguais aos da tela: a meta é
  // contada em greens inteiros, e barra contínua sugeriria meio degrau.
  if (temMeta) {
    const meta = input.meta!
    const feitos = Math.max(0, Math.min(input.degrau! - 1, meta))
    ctx.font = fontMono(700, 24)
    ctx.fillStyle = '#71717a'
    ctx.fillText(`DEGRAU ${input.degrau} DE ${meta}`, W / 2, cursorY)
    cursorY += 34
    const larguraTotal = W - 240
    const gap = 12
    const segW = (larguraTotal - gap * (meta - 1)) / meta
    for (let i = 0; i < meta; i++) {
      const x = W / 2 - larguraTotal / 2 + i * (segW + gap)
      drawRoundedRect(ctx, x, cursorY, segW, 18, 9)
      // Cheio = green já dado; o degrau atual pulsa na cor do card; o resto fica apagado.
      ctx.fillStyle = i < feitos ? accentHex : i === feitos ? `${accentHex}55` : 'rgba(255,255,255,0.08)'
      ctx.fill()
    }
    cursorY += 18 + 66
  }

  // Pernas · cada jogo com o mercado e a odd DELE
  const logos = await Promise.all(
    legs.map(l => Promise.all([
      l.homeTeamId ? loadImage(`/api/proxy/team/${l.homeTeamId}.png`) : Promise.resolve(null),
      l.awayTeamId ? loadImage(`/api/proxy/team/${l.awayTeamId}.png`) : Promise.resolve(null),
    ]))
  )

  legs.forEach((l, i) => {
    const rowY = cursorY + i * rowH
    const boxH = rowH - 18
    const [homeLogo, awayLogo] = logos[i]

    drawRoundedRect(ctx, 70, rowY, W - 140, boxH, 20)
    ctx.fillStyle = 'rgba(255,255,255,0.03)'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.07)'
    ctx.lineWidth = 1.5
    ctx.stroke()

    // Número do jogo dentro do bilhete, à esquerda: sem ele três caixas
    // parecidas viram uma lista sem ordem.
    const midY = rowY + boxH / 2
    ctx.textAlign = 'left'
    ctx.font = fontMono(700, 22)
    ctx.fillStyle = '#52525b'
    ctx.fillText(`${i + 1}`, 100, midY + 6)
    drawCircularLogo(ctx, homeLogo, 182, midY - 12, 62)
    drawCircularLogo(ctx, awayLogo, 258, midY - 12, 62)

    ctx.textAlign = 'left'
    const textoX = 320
    // Reserva a coluna da odd (desenhada em W-106, alinhada à direita): sem
    // essa folga um confronto longo como "Olimpia Asunción x Vasco da Gama"
    // encostava no número.
    const largura = W - textoX - 230
    ctx.font = fontDisplay(800, 34)
    ctx.fillStyle = '#ffffff'
    const confronto = l.awayTeamName ? `${l.homeTeamName} x ${l.awayTeamName}` : l.homeTeamName
    ctx.fillText(fitText(ctx, confronto, largura), textoX, midY - 14)

    const mercado = [l.market, l.line].filter(Boolean).join(', ')
    if (mercado) {
      ctx.font = fontSans(600, 26)
      ctx.fillStyle = '#a1a1aa'
      ctx.fillText(fitText(ctx, mercado, largura), textoX, midY + 30)
    }

    if (l.odd) {
      ctx.textAlign = 'right'
      ctx.font = fontMono(900, 38)
      ctx.fillStyle = accentHex
      ctx.fillText(l.odd.toFixed(2), W - 106, midY + 2)
    }
    ctx.textAlign = 'center'
  })
  cursorY += legs.length * rowH + 30

  // Composto: o que o produto promete, em unidade e não em reais · o valor de
  // entrada é escolha de cada um, então R$ aqui não compara com nada (mesma
  // regra de _alav_unidades no backend).
  // A frase muda com o resultado: "vira" promete futuro e ficaria mentindo em
  // cima de um pick já resolvido, e num RED o valor do composto não é o que
  // aconteceu · ali o número verdadeiro é a unidade perdida.
  const perdeu = input.result === 'RED'
  const rotuloComposto = perdeu ? 'RESULTADO'
    : input.result === 'GREEN' ? '1 UNIDADE VIROU'
    : '1 UNIDADE VIRA'
  const valorComposto = perdeu ? '−1,00u' : `${input.oddCombined.toFixed(2)}u`
  ctx.font = fontMono(700, 24)
  ctx.fillStyle = '#71717a'
  ctx.fillText(rotuloComposto, W / 2, cursorY)
  ctx.font = fontMono(900, 96)
  withGlow(ctx, `${accentHex}66`, 22, () => {
    ctx.fillStyle = accentHex
    ctx.fillText(valorComposto, W / 2, cursorY + 88)
  })
  cursorY += 96 + 60

  // Selo de resultado
  const resultLabel = rs ? rs.label : 'EM ANDAMENTO'
  ctx.font = fontDisplay(900, 60)
  const seloW = ctx.measureText(resultLabel).width + 110
  const seloGrad = ctx.createLinearGradient(0, cursorY, 0, cursorY + 104)
  seloGrad.addColorStop(0, `${accentHex}33`)
  seloGrad.addColorStop(1, `${accentHex}14`)
  drawRoundedRect(ctx, W / 2 - seloW / 2, cursorY, seloW, 104, 24)
  ctx.fillStyle = seloGrad
  ctx.fill()
  withGlow(ctx, `${accentHex}aa`, 24, () => {
    ctx.strokeStyle = accentHex
    ctx.lineWidth = 3
    ctx.stroke()
  })
  ctx.fillStyle = accentHex
  ctx.fillText(resultLabel, W / 2, cursorY + 72)
  cursorY += 104 + 80

  drawCtaFooter(ctx, cursorY, input.shareUrl)
  ctx.restore()
  drawFooterCredit(ctx)

  return toBlobPromise(canvas)
}
