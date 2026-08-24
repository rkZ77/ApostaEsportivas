/*
 * Tema claro/escuro.
 *
 * Nao ha provider e nao ha contexto: o tema e' um dado do <html>, nao da
 * arvore de componentes. Um store de modulo com `useSyncExternalStore` deixa
 * qualquer componente ler e trocar o tema sem que App.tsx precise embrulhar
 * mais uma coisa · e sem que a Navbar e o SiteHeader saiam de sincronia,
 * porque os dois leem a MESMA variavel.
 *
 * Quem realmente pinta o tema no primeiro quadro e' o script inline do
 * index.html, que roda antes do React existir. Se a leitura fosse feita so'
 * aqui, quem escolheu claro veria um flash escuro em toda visita.
 */

export type Tema = 'dark' | 'light'

/** Mesma chave lida pelo script inline do index.html. Mudar aqui exige mudar la'. */
export const CHAVE_TEMA = 'pickia_theme'

/* A cor da barra do navegador no celular (e da splash do PWA). Sao os mesmos
   valores de --surface-0 nos dois temas · quando divergirem, e' aqui que se
   ve a emenda entre a barra do sistema e o topo da pagina. */
const THEME_COLOR: Record<Tema, string> = {
  dark:  '#0a0a0c',
  light: '#ffffff',
}

function lerArmazenado(): Tema | null {
  try {
    const v = localStorage.getItem(CHAVE_TEMA)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    /* Safari em aba privada, ou site data bloqueado: o tema so' nao persiste. */
    return null
  }
}

/*
 * O <html> e' a fonte da verdade, nao o localStorage.
 *
 * Na primeira leitura os dois concordam (o script inline copiou um pro outro),
 * mas se o armazenamento estiver bloqueado so' o atributo existe · e e' ele
 * que o CSS enxerga.
 */
function lerDoDocumento(): Tema {
  if (typeof document === 'undefined') return 'dark'
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

let atual: Tema = typeof document === 'undefined' ? 'dark' : (lerArmazenado() ?? lerDoDocumento())

const inscritos = new Set<() => void>()

function aplicar(tema: Tema) {
  const raiz = document.documentElement
  /* `light` explicito e ausencia de atributo, em vez de light/dark: o escuro
     e' o padrao e mora no `:root` puro, entao ele nao precisa de marcador. */
  if (tema === 'light') raiz.dataset.theme = 'light'
  else delete raiz.dataset.theme

  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', THEME_COLOR[tema])
}

/*
 * O script inline do index.html pinta o <html>, mas nao mexe no <meta
 * theme-color> · ele nem sabe o valor. Quem escolheu o claro veria a barra do
 * navegador continuar preta ate' a primeira troca de tema. Um `aplicar` na
 * carga fecha essa fresta, e de quebra corrige o caso do localStorage ter o
 * tema e o atributo nao (script bloqueado por CSP, por exemplo).
 */
if (typeof document !== 'undefined') aplicar(atual)

export function getTema(): Tema {
  return atual
}

export function setTema(tema: Tema) {
  if (tema === atual) return
  atual = tema
  aplicar(tema)
  try { localStorage.setItem(CHAVE_TEMA, tema) } catch { /* ver lerArmazenado */ }
  inscritos.forEach(fn => fn())
}

export function alternarTema() {
  setTema(atual === 'dark' ? 'light' : 'dark')
}

export function inscrever(fn: () => void) {
  inscritos.add(fn)
  return () => { inscritos.delete(fn) }
}
