import { Link } from 'react-router-dom'
import PageShell from '../components/PageShell'

export default function Privacidade() {
  return (
    <PageShell
      title="Política de Privacidade · Pick IA"
      description="Política de Privacidade do Pick IA: quais dados coletamos, como usamos e seus direitos."
      width="prose"
      nav={false}
      bar={{ back: '/', title: 'Política de Privacidade', sub: 'Última atualização: junho de 2026' }}
      mainClassName="text-ink-2"
    >

        <div className="space-y-8 text-sm leading-relaxed">

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">1. Quem somos</h2>
            <p>
              Pick IA é um serviço de tips esportivas geradas por Inteligência Artificial, acessível em{' '}
              <span className="text-green-400">pickia.com.br</span>. O responsável pelo tratamento dos seus dados é o
              operador do serviço Pick IA, com contato disponível pelo e-mail{' '}
              <span className="text-green-400">pickia.noreply@gmail.com</span>.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">2. Dados que coletamos</h2>
            <ul className="list-disc list-inside space-y-1 text-ink-2">
              <li><span className="text-ink-2">Cadastro:</span> nome, nome de usuário, e-mail e telefone (o telefone identifica a conta e limita o trial gratuito a uma vez por pessoa)</li>
              <li><span className="text-ink-2">Pagamento:</span> histórico de transações processadas pelo MercadoPago (não armazenamos dados de cartão)</li>
              <li><span className="text-ink-2">Uso do serviço:</span> picks seguidos, comentários, reações e dados de banca</li>
              <li><span className="text-ink-2">Técnicos:</span> endereço IP, tipo de navegador e horários de acesso (para segurança e rate limiting)</li>
            </ul>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">3. Para que usamos seus dados</h2>
            <ul className="list-disc list-inside space-y-1 text-ink-2">
              <li>Criar e gerenciar sua conta</li>
              <li>Processar pagamentos e ativar seu plano</li>
              <li>Enviar e-mails transacionais (confirmação de cadastro, reset de senha, confirmação de VIP)</li>
              <li>Prevenir fraudes e abusos no sistema</li>
              <li>Cumprir obrigações legais</li>
            </ul>
            <p className="mt-3 text-ink-3">
              Não vendemos, alugamos ou compartilhamos seus dados com terceiros para fins de marketing.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">4. Base legal (LGPD)</h2>
            <p className="text-ink-2">
              Tratamos seus dados com base no <span className="text-ink-2">cumprimento de contrato</span> (art. 7º, V da LGPD)
              para a prestação do serviço, <span className="text-ink-2">obrigação legal</span> (art. 7º, II) para os dados
              financeiros, e <span className="text-ink-2">legítimo interesse</span> (art. 7º, IX) para segurança da plataforma.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">5. Com quem compartilhamos</h2>
            <ul className="list-disc list-inside space-y-1 text-ink-2">
              <li><span className="text-ink-2">MercadoPago:</span> processamento de pagamentos (dados mínimos necessários)</li>
              <li><span className="text-ink-2">Supabase:</span> armazenamento do banco de dados com criptografia em trânsito e em repouso</li>
              <li><span className="text-ink-2">Provedor de IA:</span> geração de picks por IA (dados anonimizados de partidas, sem dados pessoais)</li>
            </ul>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">6. Por quanto tempo guardamos</h2>
            <p className="text-ink-2">
              Seus dados ficam armazenados enquanto sua conta estiver ativa. Após solicitação de exclusão, apagamos
              seus dados pessoais em até 30 dias, exceto os exigidos por lei (dados financeiros por 5 anos, conforme
              legislação fiscal brasileira).
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">7. Seus direitos</h2>
            <p className="text-ink-2 mb-2">Conforme a LGPD (Lei 13.709/2018), você tem direito a:</p>
            <ul className="list-disc list-inside space-y-1 text-ink-2">
              <li>Confirmar se tratamos seus dados</li>
              <li>Acessar seus dados</li>
              <li>Corrigir dados incompletos ou desatualizados</li>
              <li>Solicitar a exclusão dos seus dados</li>
              <li>Revogar consentimento quando aplicável</li>
              <li>Portabilidade dos dados</li>
            </ul>
            <p className="mt-3 text-ink-2">
              Para exercer seus direitos, entre em contato:{' '}
              <span className="text-green-400">pickia.noreply@gmail.com</span>
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">8. Cookies</h2>
            <p className="text-ink-2">
              Usamos apenas cookies de sessão (HttpOnly) essenciais para autenticação. Não usamos cookies de
              rastreamento, publicidade ou analytics de terceiros.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">9. Segurança</h2>
            <p className="text-ink-2">
              Todos os dados são transmitidos via HTTPS (TLS). Senhas são armazenadas com hash bcrypt. Tokens de
              autenticação são cookies HttpOnly inacessíveis a JavaScript. Dados financeiros são processados
              diretamente pelo MercadoPago e não ficam em nossos servidores.
            </p>
          </section>

          <section>
            <h2 className="text-ink-1 font-bold text-base mb-3">10. Contato</h2>
            <p className="text-ink-2">
              Dúvidas sobre esta política? Fale conosco:{' '}
              <span className="text-green-400">pickia.noreply@gmail.com</span>
            </p>
          </section>

        </div>

        <div className="mt-12 pt-6 border-t border-line flex gap-4 text-xs text-ink-4">
          <Link to="/termos" className="hover:text-ink-2 transition-colors">Termos de Uso</Link>
          <Link to="/" className="hover:text-ink-2 transition-colors">Início</Link>
        </div>
    </PageShell>
  )
}
