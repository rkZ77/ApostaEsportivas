import { useState } from 'react'
import { AnimatePresence, m as motion, useDragControls } from 'framer-motion'
import { ArrowLeft, Check, ChevronUp, Copy, Ticket, Trash2, Wallet, X } from 'lucide-react'
import { cn } from '../../lib/cn'
import { fecharNoFundo } from '../../lib/fecharNoFundo'
import { chanceCombinada, limpar, oddCombinada, remover, semChance, textoDoBilhete, useBilheteMontado } from '../../lib/bilheteMontado'
import RegistrarBilhete from './RegistrarBilhete'

/*
 * A bandeja do bilhete montado (2026-10-06).
 *
 * Fechada, é uma pílula no rodapé com quantas seleções há e a chance estimada
 * · fica ACIMA da barra inferior do celular (BarraInferior mora em bottom
 * 0.75rem com ~64px de altura), senão uma cobriria a outra. Aberta, é uma
 * folha de baixo pra cima com a lista, de onde a pessoa tira o que não quer e
 * copia o texto pra colar na casa de aposta.
 *
 * Some sozinha quando o bilhete está vazio: não há nada a dizer.
 */
export default function BandejaDoBilhete() {
  const selecoes = useBilheteMontado()
  const [aberta, setAberta] = useState(false)
  const [copiado, setCopiado] = useState(false)
  const arraste = useDragControls()
  /* 'registrar' troca a lista pelo formulário da banca. Ela segura a folha
     aberta mesmo com o bilhete vazio: registrar LIMPA o bilhete, e sem isso a
     confirmação de sucesso sumiria junto com a última seleção. */
  const [modo, setModo] = useState<'lista' | 'registrar'>('lista')
  /* Produto das chances AJUSTADAS (18/10/2026) · era o do bateu/n cru, que
     dava "100%" pra 8/8 × 6/6. Ver lib/chanceAjustada. */
  const chance = chanceCombinada(selecoes)
  const faltam = semChance(selecoes)
  /* Produto das odds das casas · só quando todas as seleções têm odd. */
  const oddTotal = oddCombinada(selecoes)
  const oddJusta = chance != null && chance > 0 ? 1 / chance : null
  /* chance × odd − 1: negativo = o bilhete paga menos do que a chance vale. */
  const valor = chance != null && oddTotal != null ? chance * oddTotal - 1 : null
  const mesmoJogo = new Set(selecoes.map(s => s.fixture_id)).size < selecoes.length
  const fechar = () => { setAberta(false); setModo('lista') }

  if (!selecoes.length && !(aberta && modo === 'registrar')) return null

  const copiar = async () => {
    const texto = textoDoBilhete(selecoes)
    try {
      if (navigator.share && window.matchMedia('(pointer: coarse)').matches) {
        await navigator.share({ text: texto })
      } else {
        await navigator.clipboard.writeText(texto)
      }
      setCopiado(true)
      setTimeout(() => setCopiado(false), 2000)
    } catch { /* a pessoa cancelou o compartilhar: nada a fazer */ }
  }

  return (
    <>
      {!aberta && selecoes.length > 0 && (
        <button
          onClick={() => setAberta(true)}
          className="fixed z-40 left-1/2 -translate-x-1/2 md:left-auto md:right-6 md:translate-x-0
                     bottom-[calc(5.5rem+env(safe-area-inset-bottom))] md:bottom-24
                     h-12 pl-4 pr-3 rounded-full bg-accent text-on-fill shadow-elev
                     flex items-center gap-2.5 font-bold text-sm whitespace-nowrap active:scale-95 transition"
        >
          <Ticket size={18} />
          <span>Minhas seleções ({selecoes.length})</span>
          {chance != null && (
            <span className="font-mono text-xs bg-black/15 rounded-full px-2 py-0.5 tabular-nums">
              {Math.round(chance * 100)}%
            </span>
          )}
          <ChevronUp size={16} />
        </button>
      )}

      <AnimatePresence>
        {aberta && (
          <motion.div
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end md:items-center md:justify-center"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            {...fecharNoFundo(fechar)}
          >
            <motion.div
              role="dialog" aria-label="Minhas seleções"
              className="w-full md:max-w-md bg-surface-0 border border-line rounded-t-2xl md:rounded-lg
                         max-h-[85dvh] flex flex-col shadow-elev
                         pb-[env(safe-area-inset-bottom)]"
              initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 420, damping: 36 }}
              onClick={e => e.stopPropagation()}
              /* Arrastar pra baixo fecha (15/10/2026), pela alça e pelo
                 cabeçalho · ver o comentário gêmeo em ui/Modal. */
              drag="y" dragListener={false} dragControls={arraste}
              dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0, bottom: 0.7 }}
              onDragEnd={(_, info) => { if (info.offset.y > 110 || info.velocity.y > 600) fechar() }}
            >
              <div onPointerDown={e => arraste.start(e)} className="md:hidden flex justify-center pt-2.5 pb-1 touch-none cursor-grab" aria-hidden>
                <span className="h-1 w-10 rounded-full bg-line-strong" />
              </div>
              <div onPointerDown={e => { if (window.matchMedia('(max-width: 767px)').matches) arraste.start(e) }}
                className="px-4 pt-3 pb-3 flex items-center gap-3 border-b border-line md:touch-auto touch-none">
                {modo === 'registrar' ? (
                  <button onClick={() => setModo('lista')} aria-label="Voltar pras seleções"
                    className="w-11 h-11 -ml-2 grid place-items-center rounded-lg text-ink-3 hover:bg-surface-2"><ArrowLeft size={20} /></button>
                ) : <Ticket className="text-accent-ink" size={20} />}
                <div className="flex-1">
                  <div className="font-bold text-ink-1">{modo === 'registrar' ? 'Registrar na banca' : 'Minhas seleções'}</div>
                  <div className="text-[11px] text-ink-3">
                    {selecoes.length ? `${selecoes.length} ${selecoes.length === 1 ? 'seleção' : 'seleções'}` : 'Pronto'}
                  </div>
                </div>
                <button onClick={fechar} aria-label="Fechar"
                  className="w-11 h-11 grid place-items-center rounded-lg text-ink-3 hover:bg-surface-2"><X size={20} /></button>
              </div>

              {modo === 'registrar' ? (
                <div className="overflow-y-auto"><RegistrarBilhete selecoes={selecoes} onFechar={fechar} /></div>
              ) : (<>
              <div className="overflow-y-auto divide-y divide-line/60">
                {selecoes.map(s => (
                  <div key={s.id} className="px-4 py-3 flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] text-ink-3 truncate">{s.jogo}</div>
                      <div className="text-sm font-semibold text-ink-1">{s.descricao}</div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="font-mono text-sm font-black text-ink-1 tabular-nums">
                        {s.chance != null ? `${Math.round(s.chance * 100)}%` : '—'}
                      </div>
                      <div className="font-mono text-[11px] text-ink-3 tabular-nums">
                        {s.bateu}/{s.n}{s.odd != null ? ` @ ${s.odd.toFixed(2)}` : ''}
                      </div>
                    </div>
                    <button onClick={() => remover(s.id)} aria-label="Tirar das seleções"
                      className="w-11 h-11 grid place-items-center rounded-lg text-ink-3 hover:text-red-400 hover:bg-surface-2 shrink-0">
                      <Trash2 size={18} />
                    </button>
                  </div>
                ))}
              </div>

              <div className="px-4 py-3 border-t border-line space-y-3">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm text-ink-2">Chance estimada de todas baterem</span>
                  <span className="font-mono text-2xl font-black text-ink-1 tabular-nums">
                    {chance != null ? `${Math.round(chance * 100)}%` : '—'}
                  </span>
                </div>
                {(oddJusta != null || oddTotal != null) && (
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded-lg bg-surface-2 px-3 py-2">
                      <div className="text-[11px] text-ink-3">Odd justa</div>
                      <div className="font-mono text-lg font-black text-ink-1 tabular-nums">{oddJusta != null ? oddJusta.toFixed(2) : '—'}</div>
                    </div>
                    <div className="rounded-lg bg-surface-2 px-3 py-2">
                      <div className="text-[11px] text-ink-3">Odd combinada (estimada)</div>
                      <div className="font-mono text-lg font-black text-ink-1 tabular-nums">{oddTotal != null ? oddTotal.toFixed(2) : '—'}</div>
                    </div>
                  </div>
                )}
                {valor != null && (
                  valor <= -0.05 ? (
                    <p className="text-xs font-semibold text-yellow-400 leading-relaxed">
                      Valor {Math.round(valor * 100)}%: a odd paga menos do que a chance vale. No longo prazo, esse bilhete perde dinheiro.
                    </p>
                  ) : (
                    <p className="text-xs font-semibold text-ink-2 leading-relaxed">
                      {valor >= 0.05 ? `Valor +${Math.round(valor * 100)}%` : 'Odd justa'}: a odd paga {valor >= 0.05 ? 'mais do que' : 'perto do que'} a chance vale.
                    </p>
                  )
                )}
                <p className="text-[11px] text-ink-3 leading-relaxed">
                  {faltam > 0
                    ? `${faltam} ${faltam === 1 ? 'seleção está' : 'seleções estão'} sem chance estimada (sem odd nem média da liga, ou ${faltam === 1 ? 'entrou' : 'entraram'} no bilhete antes desta conta). Tire e ponha de novo pelo Raio-X pra recalcular. `
                    : ''}
                  Cada chance é o histórico de cada seleção ajustado pelo preço do mercado ou pela média da liga: sequência curta pesa pouco.
                  {mesmoJogo ? ' Seleções do mesmo jogo andam juntas, então aqui a conta é aproximada.' : ''}
                </p>
                <button onClick={() => setModo('registrar')}
                  className="w-full h-12 rounded-lg bg-accent text-on-fill hover:bg-accent-hover text-sm font-bold flex items-center justify-center gap-2">
                  <Wallet size={18} /> Registrar na banca
                </button>
                <div className="grid grid-cols-[auto_1fr] gap-2">
                  <button onClick={() => { limpar(); fechar() }}
                    className="h-12 px-4 rounded-lg border border-line text-sm font-semibold text-ink-2 hover:border-line-strong">
                    Limpar
                  </button>
                  <button onClick={copiar}
                    className={cn('h-12 rounded-lg border text-sm font-bold flex items-center justify-center gap-2 transition-colors',
                      copiado ? 'bg-accent/15 text-accent-ink border-accent/40' : 'border-line text-ink-1 hover:border-line-strong')}>
                    {copiado ? <><Check size={18} /> Copiado</> : <><Copy size={18} /> Copiar texto</>}
                  </button>
                </div>
              </div>
              </>)}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
