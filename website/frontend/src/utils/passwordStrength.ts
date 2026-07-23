/** Mesma regra do backend (_validate_password em routers/auth.py): 10+ caracteres, maiúscula e número. */
export function getPasswordStrength(pwd: string): { score: number; checks: { label: string; ok: boolean }[] } {
  const checks = [
    { label: 'Mínimo 10 caracteres', ok: pwd.length >= 10 },
    { label: 'Letra maiúscula',      ok: /[A-Z]/.test(pwd) },
    { label: 'Número',               ok: /\d/.test(pwd) },
  ]
  return { score: checks.filter(c => c.ok).length, checks }
}
