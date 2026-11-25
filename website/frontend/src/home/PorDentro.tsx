import { Check, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn } from '../lib/cn'

/*
 * O PRODUTO POR DENTRO · print real e o que aconteceu depois (25/11/2026,
 * pedido do usuário: "olha os prints" da página do Retoma).
 *
 * TELA REAL, DADO REAL. O texto e os números são os da leitura publicada em
 * 23/11/2026 pro jogo 1492469 (tabela raio_x_resumo_ia), renderizados no
 * componente do site (jogos/ResumoDaIA). Nada foi escrito pra página: numa
 * home cujo título é "estatística real", número inventado pra ilustrar seria
 * a própria contradição. O print é um recorte (sem o bloco de jogadores).
 *
 * O JOGO NÃO FOI ESCOLHIDO PELO RESULTADO: é a leitura de Série A mais recente
 * com jogo encerrado no dia em que a seção foi feita. A conferência mostra o
 * que errou junto com o que acertou. Se for trocar o exemplo, troque pela
 * mesma regra, e confira cada linha em match_statistics. O nome do arquivo leva
 * o fixture_id: a Cloudflare guarda 30 dias, e nome repetido serviria o antigo.
 */

const CONFERENCIA = [
  { linha: 'Mais de 1,5 gol',               deu: '2 gols',        bateu: true },
  { linha: 'Mais de 7,5 escanteios',        deu: '11 escanteios', bateu: true },
  { linha: 'Mais de 3,5 cartões amarelos',  deu: '4 amarelos',    bateu: true },
  { linha: 'Santos mais de 4,5 escanteios', deu: '9 do Santos',   bateu: true },
  { linha: 'Santos mais de 0,5 gol',        deu: '0 do Santos',   bateu: false },
  { linha: 'Santos mais de 2,5 amarelos',   deu: '2 do Santos',   bateu: false },
]

/** Moldura do print. O fundo é fixo e escuro nos dois temas porque a imagem
 *  também é: no tema claro, a borda clara em volta viraria um recorte torto. */
function Print({ src, w, h, alt, legenda }: {
  src: string; w: number; h: number; alt: string; legenda: string
}) {
  return (
    <figure className="min-w-0 max-w-[400px] w-full mx-auto lg:mx-0">
      <div className="rounded-lg border border-line overflow-hidden bg-[#0a0a0c]">
        <img src={src} width={w} height={h} alt={alt} loading="lazy" decoding="async"
          className="block w-full h-auto" />
      </div>
      <figcaption className="mt-2.5 text-[12px] leading-relaxed text-ink-3">{legenda}</figcaption>
    </figure>
  )
}

export default function PorDentro() {
  const acertos = CONFERENCIA.filter(c => c.bateu).length
  return (
    <section id="por-dentro" className="section">
      <div className="shell">
        <div className="max-w-2xl mb-10">
          <h2 className="font-display text-3xl md:text-4xl font-semibold tracking-[-0.03em] leading-[1.08] text-ink-1 mb-3">
            A análise de um jogo, <em className="font-serif text-accent-ink whitespace-nowrap">por dentro.</em>
          </h2>
          <p className="text-ink-2 text-[15px] leading-relaxed">
            Santos x Grêmio, Brasileirão, 23 de novembro. A leitura saiu às 15h44 e o jogo
            começou às 21h. Veja o que ela apontou e o que aconteceu em campo.
          </p>
        </div>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-12 items-start">
          <Print src="/prints/leitura-1492469.webp" w={716} h={1856}
            alt="Tela da leitura da IA: resumo do jogo e bloco do Santos em casa, com médias e mercados em percentual"
            legenda="Tela real do Pick IA, com a leitura publicada naquele dia (recorte)." />

          <div className="min-w-0 space-y-8">
            <Print src="/prints/mercados-1492469.webp" w={700} h={892}
              alt="Tela dos mercados do jogo em que o mandante em casa e o visitante fora apontam para o mesmo lado"
              legenda="Aqui só entram as linhas em que o mandante em casa e o visitante fora apontam para o mesmo lado." />

            <div className="rounded-lg border border-line bg-surface-1">
              <div className="px-5 py-4 border-b border-line">
                <h3 className="text-base font-semibold text-ink-1">Como terminou: Santos 0 x 2 Grêmio</h3>
                <p className="mt-1 text-[13px] leading-relaxed text-ink-3">
                  {acertos} das {CONFERENCIA.length} linhas mostradas se confirmaram. O Santos chegava melhor e perdeu.
                </p>
              </div>
              <ul className="divide-y divide-line">
                {CONFERENCIA.map(c => (
                  <li key={c.linha} className="px-5 py-3 flex items-center gap-3 text-[13px]">
                    {c.bateu
                      ? <Check className="w-4 h-4 shrink-0 text-accent-ink" aria-label="confirmou" />
                      : <X className="w-4 h-4 shrink-0 text-ink-3" aria-label="não confirmou" />}
                    <span className={cn('min-w-0 flex-1', c.bateu ? 'text-ink-1' : 'text-ink-2')}>{c.linha}</span>
                    <span className="shrink-0 font-mono text-ink-3 text-right">{c.deu}</span>
                  </li>
                ))}
              </ul>
              <div className="px-5 py-1 border-t border-line">
                <Link to="/resultados" className="inline-flex items-center min-h-[44px] text-[13px] font-semibold text-accent-ink hover:underline underline-offset-4">
                  Ver o histórico completo, acertos e erros
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
