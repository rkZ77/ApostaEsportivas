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

function drawCircularLogo(ctx: CanvasRenderingContext2D, img: HTMLImageElement | null, cx: number, cy: number, size: number) {
  if (!img) return
  const r = size / 2
  ctx.save()
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.closePath()
  ctx.fillStyle = '#18181b'
  ctx.fill()
  ctx.clip()
  ctx.drawImage(img, cx - r, cy - r, size, size)
  ctx.restore()
}

export async function buildStoryImage(input: StoryImageInput): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D não suportado')

  const rs = getResultStyle(input.result)
  const accentHex = rs?.hex ?? '#00CC00'

  // Fundo — gradiente escuro com a cor de destaque bem mais presente (chama
  // atenção no feed/story, em vez do brilho sutil de antes)
  const bg = ctx.createLinearGradient(0, 0, 0, H)
  bg.addColorStop(0, `${accentHex}40`)
  bg.addColorStop(0.35, '#000000')
  bg.addColorStop(1, '#09090b')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, W, H)

  const glow = ctx.createRadialGradient(W / 2, 420, 40, W / 2, 420, 820)
  glow.addColorStop(0, `${accentHex}88`)
  glow.addColorStop(1, 'transparent')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, W, H)

  // Logo
  const logoImg = await loadImage('/logo.png')
  if (logoImg) {
    ctx.drawImage(logoImg, W / 2 - 70, 100, 140, 140)
  }
  const brandY = logoImg ? 290 : 170
  ctx.font = '900 58px system-ui, -apple-system, sans-serif'
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
  ctx.font = '800 30px system-ui, -apple-system, sans-serif'
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
    ctx.font = '600 28px system-ui, -apple-system, sans-serif'
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

  ctx.font = '900 46px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#ffffff'
  ctx.fillText(fitText(ctx, input.homeTeamName, 340), W / 2, cursorY - 88)
  ctx.font = '700 30px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#52525b'
  ctx.fillText('vs', W / 2, cursorY + 14)
  if (input.awayTeamName) {
    ctx.font = '900 46px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#ffffff'
    ctx.fillText(fitText(ctx, input.awayTeamName, 340), W / 2, cursorY + 110)
  }

  cursorY += 190

  if (input.market) {
    const marketText = input.line ? `${input.market} · ${input.line}` : input.market
    ctx.font = '800 36px system-ui, -apple-system, sans-serif'
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
  const resultLabel = rs ? `${rs.label} ${rs.emoji}` : 'A CONFIRMAR'
  ctx.font = '900 72px system-ui, -apple-system, sans-serif'
  const resultTextW = ctx.measureText(resultLabel).width
  const resultBoxW = resultTextW + 120
  drawRoundedRect(ctx, W / 2 - resultBoxW / 2, cursorY, resultBoxW, 122, 26)
  ctx.fillStyle = `${accentHex}22`
  ctx.fill()
  ctx.strokeStyle = `${accentHex}88`
  ctx.lineWidth = 3
  ctx.stroke()
  ctx.fillStyle = accentHex
  ctx.fillText(resultLabel, W / 2, cursorY + 88)
  cursorY += 122

  // Estatísticas: odd, lucro e (se disponível) acerto geral do site
  cursorY += 90
  const hasWinRate = input.winRatePct != null
  const profitText = input.profit != null
    ? `${input.profit >= 0 ? '+' : ''}${input.profit.toFixed(2)}u`
    : `+${(input.odd - 1).toFixed(2)}u`
  const profitColor = input.profit != null ? (input.profit >= 0 ? '#4ade80' : '#f87171') : '#a1a1aa'

  const stats = [
    { label: 'ODD', value: input.odd.toFixed(2), color: '#4ade80' },
    { label: input.profit != null ? 'LUCRO' : 'LUCRO POT.', value: profitText, color: profitColor },
    ...(hasWinRate ? [{ label: 'ACERTO 30D', value: `${Math.round(input.winRatePct!)}%`, color: '#facc15' }] : []),
  ]
  const totalW = W - 200
  const colW = totalW / stats.length
  const statsX = W / 2 - totalW / 2
  stats.forEach((s, i) => {
    const cx = statsX + colW * i + colW / 2
    ctx.font = '700 24px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#71717a'
    ctx.fillText(s.label, cx, cursorY)
    ctx.font = '900 52px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = s.color
    ctx.fillText(s.value, cx, cursorY + 58)
  })

  cursorY += 150

  // ── Oferta + link (compacto · sem QR: quem vê o Story está no mesmo
  //    celular, então não dá pra escanear; um link grande e memorável
  //    funciona melhor, e deixa espaço livre pra pessoa colar o sticker
  //    de link do Instagram por cima) ─────────────────────────────────
  const pillLabel = '2 DIAS DE VIP GRÁTIS'
  ctx.font = '800 28px system-ui, -apple-system, sans-serif'
  const pillW = ctx.measureText(pillLabel).width + 64
  drawRoundedRect(ctx, W / 2 - pillW / 2, cursorY, pillW, 58, 29)
  ctx.fillStyle = '#00CC00'
  ctx.fill()
  ctx.fillStyle = '#04140a'
  ctx.fillText(pillLabel, W / 2, cursorY + 39)
  cursorY += 58 + 48

  // Mostra só o domínio (limpo, memorizável) · o link completo com ?ref= já
  // vai junto no navigator.share/clipboard, não precisa aparecer na imagem
  const displayDomain = (() => {
    try { return new URL(input.shareUrl).hostname.replace(/^www\./, '') }
    catch { return input.shareUrl.replace(/^https?:\/\//, '').split('/')[0] }
  })()
  const linkText = fitText(ctx, displayDomain, W - 320)
  ctx.font = '900 48px system-ui, -apple-system, sans-serif'
  const linkTextW = ctx.measureText(linkText).width
  const arrowGap = 28
  const arrowW = ctx.measureText('→').width
  const btnPadX = 56
  const btnW = linkTextW + arrowGap + arrowW + btnPadX * 2
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
  ctx.fillStyle = accentHex
  ctx.fillText('→', textX + linkTextW + arrowGap, textY)
  ctx.textAlign = 'center'

  // Rodapé
  ctx.font = '600 23px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#3f3f46'
  ctx.fillText('Pick IA · Tips por Inteligência Artificial', W / 2, H - 60)

  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error('Falha ao gerar imagem'))
    }, 'image/png', 0.95)
  })
}

// ── Helpers compartilhados pelos cards abaixo (resultado geral / jogos do dia) ──
function drawBrandHeader(ctx: CanvasRenderingContext2D, logoImg: HTMLImageElement | null): number {
  if (logoImg) {
    ctx.drawImage(logoImg, W / 2 - 70, 100, 140, 140)
  }
  const brandY = logoImg ? 290 : 170
  ctx.font = '900 58px system-ui, -apple-system, sans-serif'
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

function drawCtaFooter(ctx: CanvasRenderingContext2D, cursorY: number, shareUrl: string, accentHex: string): void {
  const pillLabel = '2 DIAS DE VIP GRÁTIS'
  ctx.font = '800 28px system-ui, -apple-system, sans-serif'
  const pillW = ctx.measureText(pillLabel).width + 64
  drawRoundedRect(ctx, W / 2 - pillW / 2, cursorY, pillW, 58, 29)
  ctx.fillStyle = '#00CC00'
  ctx.fill()
  ctx.fillStyle = '#04140a'
  ctx.fillText(pillLabel, W / 2, cursorY + 39)
  cursorY += 58 + 48

  const displayDomain = (() => {
    try { return new URL(shareUrl).hostname.replace(/^www\./, '') }
    catch { return shareUrl.replace(/^https?:\/\//, '').split('/')[0] }
  })()
  const linkText = fitText(ctx, displayDomain, W - 320)
  ctx.font = '900 48px system-ui, -apple-system, sans-serif'
  const linkTextW = ctx.measureText(linkText).width
  const arrowGap = 28
  const arrowW = ctx.measureText('→').width
  const btnPadX = 56
  const btnW = linkTextW + arrowGap + arrowW + btnPadX * 2
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
  ctx.fillStyle = accentHex
  ctx.fillText('→', textX + linkTextW + arrowGap, textY)
  ctx.textAlign = 'center'

  ctx.font = '600 23px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#3f3f46'
  ctx.fillText('Pick IA · Tips por Inteligência Artificial', W / 2, H - 60)
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
}

export async function buildResultsStoryImage(input: ResultsStoryInput): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D não suportado')

  const accentHex = '#00CC00'

  const bg = ctx.createLinearGradient(0, 0, 0, H)
  bg.addColorStop(0, '#000000')
  bg.addColorStop(1, '#09090b')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, W, H)

  const glow = ctx.createRadialGradient(W / 2, 420, 40, W / 2, 420, 720)
  glow.addColorStop(0, `${accentHex}33`)
  glow.addColorStop(1, 'transparent')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, W, H)

  const logoImg = await loadImage('/logo.png')
  const brandY = drawBrandHeader(ctx, logoImg)

  let cursorY = brandY + 56
  ctx.font = '800 30px system-ui, -apple-system, sans-serif'
  const badgeLabel = 'RESULTADOS DA IA'
  const badgeTextW = ctx.measureText(badgeLabel).width
  const badgeW = badgeTextW + 80
  drawRoundedRect(ctx, W / 2 - badgeW / 2, cursorY, badgeW, 64, 32)
  ctx.fillStyle = `${accentHex}22`
  ctx.fill()
  ctx.strokeStyle = `${accentHex}66`
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.fillStyle = accentHex
  ctx.fillText(badgeLabel, W / 2, cursorY + 43)
  cursorY += 64

  // Win rate em destaque
  cursorY += 180
  ctx.font = '900 220px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#ffffff'
  ctx.fillText(`${Math.round(input.winRatePct)}%`, W / 2, cursorY)
  ctx.font = '700 34px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#71717a'
  ctx.fillText('WIN RATE', W / 2, cursorY + 54)

  // Estatísticas: total, greens, lucro
  cursorY += 150
  const profitText = `${input.profit >= 0 ? '+' : ''}${input.profit.toFixed(1)}u`
  const stats = [
    { label: 'PICKS', value: String(input.total), color: '#ffffff' },
    { label: 'GREENS', value: String(input.greens), color: '#4ade80' },
    { label: 'LUCRO', value: profitText, color: input.profit >= 0 ? '#4ade80' : '#f87171' },
  ]
  const totalW = W - 200
  const colW = totalW / stats.length
  const statsX = W / 2 - totalW / 2
  stats.forEach((s, i) => {
    const cx = statsX + colW * i + colW / 2
    ctx.font = '700 26px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#71717a'
    ctx.fillText(s.label, cx, cursorY)
    ctx.font = '900 58px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = s.color
    ctx.fillText(s.value, cx, cursorY + 64)
  })

  cursorY += 220
  ctx.font = '600 28px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#52525b'
  ctx.fillText('Histórico 100% auditável e público', W / 2, cursorY)

  cursorY += 90
  drawCtaFooter(ctx, cursorY, input.shareUrl, accentHex)

  return toBlobPromise(canvas)
}

// ── Card: jogos de hoje que a IA vai analisar ───────────────────────────────
export interface TodayGameItem {
  homeTeamName: string
  awayTeamName: string
  homeTeamId?: number | null
  awayTeamId?: number | null
  leagueName?: string
  matchDatetime: string
}

export interface TodayGamesStoryInput {
  games: TodayGameItem[]
  shareUrl: string
}

export async function buildTodayGamesStoryImage(input: TodayGamesStoryInput): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D não suportado')

  const accentHex = '#facc15'

  const bg = ctx.createLinearGradient(0, 0, 0, H)
  bg.addColorStop(0, '#000000')
  bg.addColorStop(1, '#09090b')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, W, H)

  const glow = ctx.createRadialGradient(W / 2, 380, 40, W / 2, 380, 680)
  glow.addColorStop(0, `${accentHex}22`)
  glow.addColorStop(1, 'transparent')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, W, H)

  const logoImg = await loadImage('/logo.png')
  const brandY = drawBrandHeader(ctx, logoImg)

  let cursorY = brandY + 56
  ctx.font = '800 28px system-ui, -apple-system, sans-serif'
  const badgeLabel = 'JOGOS DE HOJE · A IA VAI ANALISAR'
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

  const games = input.games.slice(0, 8)
  const rowH = games.length > 6 ? 128 : 154
  const logoSize = games.length > 6 ? 44 : 52

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

    const midY = rowY + (rowH - 16) / 2
    drawCircularLogo(ctx, homeLogo, 70 + 70, midY, logoSize)
    drawCircularLogo(ctx, awayLogo, W - 70 - 70, midY, logoSize)

    ctx.textAlign = 'center'
    ctx.font = '800 30px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#ffffff'
    ctx.fillText(fitText(ctx, g.homeTeamName, 300), W / 2, midY - 14)
    ctx.font = '600 24px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#52525b'
    ctx.fillText('vs', W / 2, midY + 20)
    ctx.font = '800 30px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#ffffff'
    ctx.fillText(fitText(ctx, g.awayTeamName, 300), W / 2, midY + 54)

    if (g.leagueName) {
      ctx.font = '600 20px system-ui, -apple-system, sans-serif'
      ctx.fillStyle = '#71717a'
      ctx.fillText(fitText(ctx, g.leagueName, 260), W / 2, midY + 78)
    }
  })

  cursorY += games.length * rowH + 60
  drawCtaFooter(ctx, cursorY, input.shareUrl, accentHex)

  return toBlobPromise(canvas)
}
