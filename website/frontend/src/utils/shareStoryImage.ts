import QRCode from 'qrcode'
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

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.split(' ')
  const lines: string[] = []
  let current = ''
  for (const word of words) {
    const test = current ? `${current} ${word}` : word
    if (current && ctx.measureText(test).width > maxWidth) {
      lines.push(current)
      current = word
    } else {
      current = test
    }
  }
  if (current) lines.push(current)
  return lines
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

  // Fundo
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

  // Logo
  const logoImg = await loadImage('/logo.png')
  if (logoImg) {
    ctx.drawImage(logoImg, W / 2 - 70, 90, 140, 140)
  }
  const brandY = logoImg ? 280 : 160
  ctx.font = '900 56px system-ui, -apple-system, sans-serif'
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
  const badgeY = brandY + 50
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
    cursorY += 56
    ctx.font = '600 28px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#71717a'
    ctx.fillText(fitText(ctx, input.leagueName, W - 160), W / 2, cursorY)
  }

  // Times
  cursorY += 130
  const [homeLogo, awayLogo] = await Promise.all([
    input.homeTeamId ? loadImage(`/api/proxy/team/${input.homeTeamId}.png`) : Promise.resolve(null),
    input.awayTeamId ? loadImage(`/api/proxy/team/${input.awayTeamId}.png`) : Promise.resolve(null),
  ])

  const logoSize = 110
  drawCircularLogo(ctx, homeLogo, W / 2 - 250, cursorY, logoSize)
  drawCircularLogo(ctx, awayLogo, W / 2 + 250, cursorY, logoSize)

  ctx.font = '900 44px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#ffffff'
  ctx.fillText(fitText(ctx, input.homeTeamName, 340), W / 2, cursorY - 84)
  ctx.font = '700 28px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#52525b'
  ctx.fillText('vs', W / 2, cursorY + 12)
  if (input.awayTeamName) {
    ctx.font = '900 44px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#ffffff'
    ctx.fillText(fitText(ctx, input.awayTeamName, 340), W / 2, cursorY + 104)
  }

  cursorY += 150

  if (input.market) {
    ctx.font = '600 27px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#a1a1aa'
    const marketText = input.line ? `${input.market} · ${input.line}` : input.market
    ctx.fillText(fitText(ctx, marketText, W - 160), W / 2, cursorY)
    cursorY += 52
  }

  // Selo de resultado
  cursorY += 34
  const resultLabel = rs ? `${rs.label} ${rs.emoji}` : 'A CONFIRMAR'
  ctx.font = '900 68px system-ui, -apple-system, sans-serif'
  const resultTextW = ctx.measureText(resultLabel).width
  const resultBoxW = resultTextW + 110
  drawRoundedRect(ctx, W / 2 - resultBoxW / 2, cursorY, resultBoxW, 114, 24)
  ctx.fillStyle = `${accentHex}22`
  ctx.fill()
  ctx.strokeStyle = `${accentHex}88`
  ctx.lineWidth = 3
  ctx.stroke()
  ctx.fillStyle = accentHex
  ctx.fillText(resultLabel, W / 2, cursorY + 83)
  cursorY += 114

  // Odd + Lucro
  cursorY += 64
  const colW = 320
  const gap = 40
  const statsTotalW = colW * 2 + gap
  const statsX = W / 2 - statsTotalW / 2

  const drawStat = (x: number, label: string, value: string, color: string) => {
    ctx.font = '700 25px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#71717a'
    ctx.fillText(label, x + colW / 2, cursorY)
    ctx.font = '900 54px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = color
    ctx.fillText(value, x + colW / 2, cursorY + 58)
  }

  drawStat(statsX, 'ODD', input.odd.toFixed(2), '#4ade80')
  const profitText = input.profit != null
    ? `${input.profit >= 0 ? '+' : ''}${input.profit.toFixed(2)}u`
    : `+${(input.odd - 1).toFixed(2)}u`
  const profitColor = input.profit != null ? (input.profit >= 0 ? '#4ade80' : '#f87171') : '#a1a1aa'
  drawStat(statsX + colW + gap, input.profit != null ? 'LUCRO' : 'LUCRO POT.', profitText, profitColor)

  cursorY += 118

  // ── Painel de chamada: prova social + oferta de trial ───────────────────
  cursorY += 50
  const panelW = W - 160
  const panelX = W / 2 - panelW / 2
  const panelPadX = 56

  const pillLabel = '2 DIAS DE VIP GRÁTIS'
  ctx.font = '800 26px system-ui, -apple-system, sans-serif'
  const pillW = ctx.measureText(pillLabel).width + 56

  ctx.font = '800 36px system-ui, -apple-system, sans-serif'
  const headline = 'Quer receber picks assim antes do jogo começar?'
  const headlineLines = wrapText(ctx, headline, panelW - panelPadX * 2)

  const hasWinRate = input.winRatePct != null
  let panelH = 40 + 52 + 28 + headlineLines.length * 46 + 20
  if (hasWinRate) panelH += 40
  panelH += 32

  drawRoundedRect(ctx, panelX, cursorY, panelW, panelH, 28)
  ctx.fillStyle = 'rgba(255,255,255,0.04)'
  ctx.fill()
  ctx.strokeStyle = `${accentHex}55`
  ctx.lineWidth = 2
  ctx.stroke()

  let panelCursor = cursorY + 40

  // Pill do trial
  drawRoundedRect(ctx, W / 2 - pillW / 2, panelCursor, pillW, 52, 26)
  ctx.fillStyle = '#00CC00'
  ctx.fill()
  ctx.font = '800 26px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#04140a'
  ctx.fillText(pillLabel, W / 2, panelCursor + 35)
  panelCursor += 52 + 28

  // Headline
  ctx.font = '800 36px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#ffffff'
  for (const line of headlineLines) {
    ctx.fillText(line, W / 2, panelCursor)
    panelCursor += 46
  }

  // Prova social (win rate real do site, se disponível)
  if (hasWinRate) {
    panelCursor += 6
    ctx.font = '700 27px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = '#a1a1aa'
    ctx.fillText(`${Math.round(input.winRatePct!)}% de acerto nos últimos 30 dias`, W / 2, panelCursor)
  }

  cursorY += panelH + 56

  // QR code
  const qrSize = 260
  const qrCanvas = document.createElement('canvas')
  await QRCode.toCanvas(qrCanvas, input.shareUrl, {
    width: qrSize,
    margin: 1,
    color: { dark: '#000000ff', light: '#ffffffff' },
  })
  const qrX = W / 2 - qrSize / 2
  const qrY = cursorY
  drawRoundedRect(ctx, qrX - 20, qrY - 20, qrSize + 40, qrSize + 40, 20)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.drawImage(qrCanvas, qrX, qrY, qrSize, qrSize)

  cursorY = qrY + qrSize + 62
  ctx.font = '700 25px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#d4d4d8'
  ctx.fillText('Escaneie e comece agora', W / 2, cursorY)
  cursorY += 40
  ctx.font = '600 23px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#52525b'
  ctx.fillText(fitText(ctx, input.shareUrl.replace(/^https?:\/\//, ''), W - 120), W / 2, cursorY)

  // Rodapé
  ctx.font = '600 23px system-ui, -apple-system, sans-serif'
  ctx.fillStyle = '#3f3f46'
  ctx.fillText('Pick IA · Tips por Inteligência Artificial', W / 2, H - 50)

  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error('Falha ao gerar imagem'))
    }, 'image/png', 0.95)
  })
}
