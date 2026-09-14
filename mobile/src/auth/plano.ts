import type { Usuario } from '../api/types'

/*
 * O NOME DO PLANO NA TELA, num lugar só.
 *
 * Estava escrito à mão em duas telas (home e perfil) com o mesmo ternário
 * encadeado, e as duas diziam "VIP". Desde 12/09/2026 existem dois produtos
 * pagos e "VIP" deixou de ser o nome de qualquer um deles: quem assina lê
 * "Pick IA" ou "Pick IA Pro" no site inteiro, e um app que chama a mesma
 * assinatura de outra coisa parece ser de outro serviço.
 *
 * `plan_tier` ausente vale 'pro', igual em todo o resto: quem assinou antes da
 * mudança tinha tudo, e um campo que ainda não chegou não pode rebaixar
 * ninguém na tela.
 */
export function rotuloDoPlano(usuario: Usuario | null | undefined): string {
  if (!usuario) return 'Free'
  if (usuario.plan === 'admin') return 'Admin'
  if (usuario.plan === 'trial') return 'Trial'
  if (usuario.plan !== 'vip') return 'Free'
  return (usuario.plan_tier ?? 'pro') === 'base' ? 'Pick IA' : 'Pick IA Pro'
}
