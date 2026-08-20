import PageShell from '../components/PageShell'
import AlavancagemPanel from '../components/AlavancagemPanel'

/*
 * Alavancagem em página própria.
 *
 * Casca fina de propósito: o conteúdo mora em components/AlavancagemPanel,
 * porque ele é sub-página de DOIS lugares (Minha Banca e a aba de Meus Picks)
 * e ainda é o destino do card da aba Alavancagem em /picks. Três entradas, um
 * conteúdo · o porquê de cada decisão está no comentário do painel.
 */
export default function BancaAlavancagem() {
  return (
    <PageShell
      title="Alavancagem"
      description="Seus caminhos de alavancagem, separados da banca."
      noindex
      width="full"
      bar={{
        back: '/banca',
        title: 'Alavancagem',
        sub: 'Contabilizada à parte da banca · só o caminho encerrado vira saldo',
      }}
      mainClassName="space-y-5"
    >
      <AlavancagemPanel />
    </PageShell>
  )
}
