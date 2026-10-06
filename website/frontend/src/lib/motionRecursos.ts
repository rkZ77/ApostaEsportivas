/*
 * O motor de animação do framer-motion, num chunk próprio que chega DEPOIS.
 *
 * Importado só por `import()` em main.tsx · ver o comentário de LazyMotion lá.
 * `domMax`, e não o `domAnimation` menor, porque três abas usam `layoutId`
 * (o sublinhado que desliza entre Picks, Meus Picks e Jogos) e o card do ao
 * vivo usa `layout` · os dois só existem no pacote completo.
 */
export { domMax as default } from 'framer-motion'
