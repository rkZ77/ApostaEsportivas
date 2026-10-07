import { createLucideIcon } from 'lucide-react'

/*
 * Bola de futebol no traço do lucide (2026-10-07, pedido do usuário: a aba
 * Jogos usava um troféu).
 *
 * O lucide não tem bola de futebol · só a de vôlei, que seria o esporte
 * errado. `createLucideIcon` faz deste um ícone igual aos outros em tudo que
 * importa: grid de 24, traço que segue `strokeWidth`, cor por `currentColor`
 * e o tipo `LucideIcon`, que é o que a gaveta do celular e a Navbar aceitam.
 *
 * O desenho: o pentágono do meio e as cinco costuras que saem dele até a
 * borda, nos mesmos ângulos dos vértices.
 */
const BolaDeFutebol = createLucideIcon('BolaDeFutebol', [
  ['circle', { cx: '12', cy: '12', r: '10', key: 'borda' }],
  ['path', { d: 'M12 8l3.8 2.76-1.45 4.48h-4.7L8.2 10.76z', key: 'pentagono' }],
  ['path', { d: 'M12 8V2', key: 'c1' }],
  ['path', { d: 'M15.8 10.76l5.7-1.85', key: 'c2' }],
  ['path', { d: 'M14.35 15.24l3.53 4.85', key: 'c3' }],
  ['path', { d: 'M9.65 15.24l-3.53 4.85', key: 'c4' }],
  ['path', { d: 'M8.2 10.76L2.5 8.91', key: 'c5' }],
])

export default BolaDeFutebol
