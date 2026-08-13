/**
 * Os mesmos tokens visuais do site, em forma consumível pelo React Native.
 *
 * Espelho de `website/frontend/src/index.css`. Os valores foram copiados de
 * lá, não redecididos aqui: a regra do projeto é que mudar cor significa
 * editar o token, e o app precisa herdar a mesma identidade. Se um token
 * mudar no site, mude aqui também -- é a única duplicação aceita, porque o
 * RN não lê CSS custom properties.
 */

export const cores = {
  /* superfícies */
  surface0: '#0a0a0c', // fundo de página
  surface1: '#141418', // card
  surface2: '#1f1f24', // card elevado, input
  surface3: '#2b2b31', // hover, estado ativo

  /* bordas */
  line: '#232329',
  lineStrong: '#33333a',

  /* texto -- os contrastes são os validados no site */
  ink1: '#fafafa', // título, número
  ink2: '#c7c7cf', // corpo
  ink3: '#94949e', // apoio, rótulo
  ink4: '#75757f', // só texto grande

  /* marca */
  accent: '#00CC00',
  accentHover: '#1ae01a',
  accentPress: '#00aa00',

  /* estados de resultado -- mesma semântica de utils/resultStyle.ts no site */
  green: '#00CC00',
  red: '#ef4444',
  amber: '#f59e0b',
  blue: '#3b82f6',
} as const

export const espaco = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const

export const raio = {
  sm: 8,
  md: 12,
  lg: 16,
  pill: 999,
} as const

export const fonte = {
  xs: 11,
  sm: 13,
  base: 15,
  lg: 17,
  xl: 20,
  xxl: 26,
  display: 32,
} as const

export const peso = {
  normal: '400',
  medio: '500',
  semi: '600',
  bold: '700',
} as const

/** Duração de animação, herdada de --dur-1/--dur-2 do site. */
export const duracao = {
  rapida: 150,
  media: 240,
} as const
