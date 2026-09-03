import { Link } from 'react-router-dom'
import PageShell from '../components/PageShell'

export default function Termos() {
  return (
    <PageShell
      /* Texto estático, zero requisição · o portão de revelação só adicionaria
         um fade em cima de uma tela que já está pronta. Ver useRevelacao. */
      revelacao={false}
      title="Termos de Uso | Pick IA"
      description="Termos de Uso do Pick IA: regras de uso da plataforma, assinaturas e responsabilidades."
      canonical="https://pickia.com.br/termos"
      width="prose"
      nav={false}
      bar={{ back: '/', title: 'Termos de Uso', sub: 'Última atualização: junho de 2026' }}
      mainClassName="text-ink-2"
    >

        <div className="space-y-8 text-sm leading-relaxed">

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">1. Aceitação dos termos</h2>
            <p className="text-ink-2">
              Ao criar uma conta ou utilizar o Pick IA (<span className="text-green-400">pickia.com.br</span>), você
              declara ter lido, compreendido e concordado com estes Termos de Uso. Se não concordar, não utilize o serviço.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">2. O que é o Pick IA</h2>
            <p className="text-ink-2">
              O Pick IA é uma plataforma de análise esportiva que utiliza Inteligência Artificial para gerar
              sugestões de apostas (picks). O serviço tem caráter <span className="text-ink-1 font-semibold">educacional e de entretenimento</span>.{' '}
              <span className="text-yellow-400 font-semibold">As sugestões não constituem conselho financeiro ou garantia de lucro.</span>
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">3. Restrição de idade</h2>
            <p className="text-ink-2">
              O uso do Pick IA é restrito a maiores de <span className="text-ink-1 font-semibold">18 anos</span>. Ao
              criar uma conta, você confirma ter atingido a maioridade legal no seu país de residência.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">4. Isenção de responsabilidade</h2>
            <div className="bg-yellow-400/5 border border-yellow-400/20 rounded-lg p-4 text-ink-2 space-y-2">
              <p>
                As sugestões geradas pelo Pick IA são baseadas em análise estatística e modelos de IA. Resultados
                passados não garantem resultados futuros.
              </p>
              <p>
                O Pick IA <span className="text-ink-1 font-semibold">não se responsabiliza por perdas financeiras</span> decorrentes
                do uso das sugestões. Aposte apenas o que você pode perder. Jogue com responsabilidade.
              </p>
              <p>
                A prática de apostas esportivas pode envolver riscos de dependência. Se precisar de ajuda, acesse:{' '}
                <span className="text-green-400">jogadores-anonimos.org.br</span>
              </p>
            </div>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">5. Planos e pagamentos</h2>
            <ul className="list-disc list-inside space-y-2 text-ink-2">
              <li>Os planos VIP dão acesso a picks completos pelo período contratado (mensal, trimestral, semestral ou anual)</li>
              <li>O pagamento é processado pelo MercadoPago e cobrado no ato da contratação</li>
              <li>Após ativação, o plano não é reembolsável, exceto nos casos previstos pelo Código de Defesa do Consumidor (CDC)</li>
              <li>O trial gratuito de 2 dias é disponibilizado uma única vez por conta, liberado após a confirmação do e-mail</li>
              <li>Preços podem ser alterados mediante aviso prévio de 30 dias</li>
            </ul>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">6. Conta do usuário</h2>
            <ul className="list-disc list-inside space-y-2 text-ink-2">
              <li>Você é responsável pela confidencialidade da sua senha</li>
              <li>Uma conta por número de telefone. Contas duplicadas podem ser suspensas</li>
              <li>É proibido compartilhar credenciais de acesso</li>
              <li>Uso indevido ou fraude resulta em cancelamento imediato sem reembolso</li>
            </ul>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">7. Conduta na plataforma</h2>
            <p className="text-ink-2 mb-2">É proibido no chat e comentários:</p>
            <ul className="list-disc list-inside space-y-1 text-ink-2">
              <li>Linguagem ofensiva, discriminatória ou de ódio</li>
              <li>Spam ou divulgação de serviços concorrentes</li>
              <li>Conteúdo ilegal ou que viole direitos de terceiros</li>
            </ul>
            <p className="mt-3 text-ink-2">
              Violações podem resultar em suspensão ou exclusão da conta a critério do Pick IA.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">8. Propriedade intelectual</h2>
            <p className="text-ink-2">
              Todo o conteúdo gerado pela plataforma (picks, análises, relatórios) é de propriedade do Pick IA.
              É proibida a reprodução, venda ou distribuição sem autorização expressa por escrito.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">9. Cancelamento e exclusão de conta</h2>
            <p className="text-ink-2">
              Você pode solicitar a exclusão da sua conta a qualquer momento pelo e-mail{' '}
              <span className="text-green-400">pickia.noreply@gmail.com</span>. O plano em vigor não será reembolsado,
              mas o acesso permanece ativo até o fim do período pago.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">10. Legislação aplicável</h2>
            <p className="text-ink-2">
              Estes termos são regidos pelas leis brasileiras. Fica eleito o foro da comarca de São Paulo/SP para
              dirimir eventuais conflitos, com renúncia a qualquer outro, por mais privilegiado que seja.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">11. Alterações nestes termos</h2>
            <p className="text-ink-2">
              Podemos atualizar estes termos periodicamente. Alterações significativas serão comunicadas por e-mail
              com 30 dias de antecedência. O uso continuado após a data de vigência indica aceitação.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">12. Contato</h2>
            <p className="text-ink-2">
              Dúvidas sobre estes termos:{' '}
              <span className="text-green-400">pickia.noreply@gmail.com</span>
            </p>
          </section>

        </div>

        <div className="mt-12 pt-6 border-t border-line flex gap-4 text-xs text-ink-4">
          <Link to="/privacidade" className="hover:text-ink-2 transition-colors">Política de Privacidade</Link>
          <Link to="/" className="hover:text-ink-2 transition-colors">Início</Link>
        </div>
    </PageShell>
  )
}
