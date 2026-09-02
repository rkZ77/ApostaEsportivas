import { useEffect, useState } from 'react'
import { Layers } from 'lucide-react'
import api from '../services/api'
import { Skeleton } from './ui'
import BlocoAmostra, { type Amostra } from './BlocoAmostra'

/*
 * "Os jogos que o motor olhou" · dentro do Entenda esta análise.
 *
 * POR QUE ISTO NÃO É O MarketForm QUE JÁ EXISTE
 * ---------------------------------------------
 * O MarketForm reconsulta o banco e monta uma série pelo contador do mercado.
 * É útil e continua ali · ele mostra GREEN/RED barra a barra. Mas é uma
 * SEGUNDA leitura, e uma segunda leitura pode divergir do que decidiu. Já
 * divergiu duas vezes em produção:
 *
 *   · por mando, em 08/08 · a série contava jogos de outro time;
 *   · por competição, em jogo de copa · o motor lê TODAS as competições
 *     (a competição sozinha não acumula jogo suficiente) e a consulta lia só a
 *     liga, então a tela mostrava três jogos onde a decisão usou quinze.
 *
 * Este bloco não consulta histórico nenhum. Ele mostra o retrato que o próprio
 * motor gravou no instante da escolha. Por construção não tem como divergir ·
 * é o mesmo objeto que entrou na conta.
 *
 * E vem com o CONTEXTO DO CONFRONTO junto, que o motor sempre calculou e nunca
 * chegava à tela: se é clássico, se é jogo de volta, o placar da ida e quantos
 * gols faltam para virar o agregado. Média sem contexto explica o número; com
 * contexto explica o jogo.
 *
 * TETO DE 10 JOGOS por time. O motor lê mais do que isso · `jogos_lidos` diz
 * quantos, e a tela mostra "10 de 34" em vez de fingir que a amostra era dez.
 *
 * Pick anterior a 27/08 não tem amostra gravada e o bloco simplesmente não
 * aparece · melhor que reconsultar e mostrar uma amostra que talvez não seja a
 * que decidiu, que é justamente o defeito que este componente fecha.
 */

export default function AmostraDoMotor({
  pickId, pickType, mercado, jogador, linha,
}: {
  pickId: number
  pickType: string
  /* CONTEXTO DO PICK DE JOGADOR (02/09).
   *
   * A amostra dele é uma fileira de números soltos: "3 2 1 4 2 2 0 3 2 1".
   * Isso não é informação, é um monte de dígito · o que transforma em leitura
   * é saber de QUE mercado são e QUAL linha precisava ser batida. Com a linha,
   * a mesma fileira responde sozinha "bateu em 7 das 10".
   *
   * Vem por prop, do card, e não de uma consulta nova: quem já tem o número na
   * tela é quem abriu o modal. O endpoint também devolve os três (a partir de
   * 02/09), e eles servem de reserva para quem abre a amostra sem card por
   * perto, como o painel de auditoria. */
  mercado?: string
  jogador?: string
  linha?: number
}) {
  const [amostra, setAmostra] = useState<Amostra | null>(null)
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    let vivo = true
    setCarregando(true)
    api.get(`/suggestions/${pickId}/amostra`, { params: { pick_type: pickType } })
      .then(r => { if (vivo) setAmostra(r.data?.available ? r.data.amostra : null) })
      .catch(() => { if (vivo) setAmostra(null) })
      .finally(() => { if (vivo) setCarregando(false) })
    return () => { vivo = false }
  }, [pickId, pickType])

  if (carregando) return <Skeleton className="h-24 w-full rounded-lg" />
  if (!amostra) return null

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <Layers className="w-3.5 h-3.5 text-ink-4" />
        <span className="panel-label">Os jogos que o motor olhou</span>
      </div>
      <BlocoAmostra
        amostra={amostra}
        mercado={mercado ?? amostra.mercado}
        jogador={jogador ?? amostra.jogador}
        linha={linha ?? amostra.linha}
      />
      <p className="text-[10px] text-ink-4 leading-relaxed mt-2">
        Esta é a amostra que gerou a análise, exatamente como o motor a leu no
        momento da escolha, não é uma consulta refeita depois.
      </p>
    </div>
  )
}
