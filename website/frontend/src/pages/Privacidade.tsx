import { Link } from 'react-router-dom'
import { Helmet } from 'react-helmet-async'
import { ChevronLeft } from 'lucide-react'
import Footer from '../components/Footer'

export default function Privacidade() {
  return (
    // bg-black e nao bg-zinc-950: as outras 20 paginas usam preto, e a
    // diferenca de tom aparecia ao navegar entre elas.
    <div className="min-h-screen bg-black text-zinc-300 flex flex-col">
      <Helmet>
        <title>Política de Privacidade · Pick IA</title>
        <meta name="description" content="Política de Privacidade do Pick IA: quais dados coletamos, como usamos e seus direitos." />
      </Helmet>
      <div className="max-w-3xl mx-auto px-4 py-12 flex-1 w-full">

        {/* Alvo de toque de 44px, como o BackButton do resto do site. A seta
            de texto que estava aqui era pequena demais pra dedo, e o site e'
            mobile-first. */}
        <Link to="/"
          className="inline-flex items-center gap-2 h-11 pr-4 text-sm text-zinc-500 hover:text-green-400 transition-colors mb-8">
          <span className="flex items-center justify-center w-11 h-11 rounded-full border border-zinc-800">
            <ChevronLeft className="w-4 h-4" />
          </span>
          Voltar
        </Link>

        <h1 className="text-3xl font-black text-white mb-2">Política de Privacidade</h1>
        <p className="text-zinc-500 text-sm mb-10">Última atualização: junho de 2026</p>

        <div className="space-y-8 text-sm leading-relaxed">

          <section>
            <h2 className="text-white font-bold text-base mb-3">1. Quem somos</h2>
            <p>
              Pick IA é um serviço de tips esportivas geradas por Inteligência Artificial, acessível em{' '}
              <span className="text-green-400">pickia.com.br</span>. O responsável pelo tratamento dos seus dados é o
              operador do serviço Pick IA, com contato disponível pelo e-mail{' '}
              <span className="text-green-400">pickia.noreply@gmail.com</span>.
            </p>
          </section>

          <section>
            <h2 className="text-white font-bold text-base mb-3">2. Dados que coletamos</h2>
            <ul className="list-disc list-inside space-y-1 text-zinc-400">
              <li><span className="text-zinc-300">Cadastro:</span> nome, e-mail, telefone e CPF (exigido para trial gratuito e cumprimento de obrigações legais)</li>
              <li><span className="text-zinc-300">Pagamento:</span> histórico de transações processadas pelo MercadoPago (não armazenamos dados de cartão)</li>
              <li><span className="text-zinc-300">Uso do serviço:</span> picks seguidos, comentários, reações e dados de banca</li>
              <li><span className="text-zinc-300">Técnicos:</span> endereço IP, tipo de navegador e horários de acesso (para segurança e rate limiting)</li>
            </ul>
          </section>

          <section>
            <h2 className="text-white font-bold text-base mb-3">3. Para que usamos seus dados</h2>
            <ul className="list-disc list-inside space-y-1 text-zinc-400">
              <li>Criar e gerenciar sua conta</li>
              <li>Processar pagamentos e ativar seu plano</li>
              <li>Enviar e-mails transacionais (confirmação de cadastro, reset de senha, confirmação de VIP)</li>
              <li>Prevenir fraudes e abusos no sistema</li>
              <li>Cumprir obrigações legais</li>
            </ul>
            <p className="mt-3 text-zinc-500">
              Não vendemos, alugamos ou compartilhamos seus dados com terceiros para fins de marketing.
            </p>
          </section>

          <section>
            <h2 className="text-white font-bold text-base mb-3">4. Base legal (LGPD)</h2>
            <p className="text-zinc-400">
              Tratamos seus dados com base no <span className="text-zinc-300">cumprimento de contrato</span> (art. 7º, V da LGPD)
              para a prestação do serviço, <span className="text-zinc-300">obrigação legal</span> (art. 7º, II) para CPF e dados
              financeiros, e <span className="text-zinc-300">legítimo interesse</span> (art. 7º, IX) para segurança da plataforma.
            </p>
          </section>

          <section>
            <h2 className="text-white font-bold text-base mb-3">5. Com quem compartilhamos</h2>
            <ul className="list-disc list-inside space-y-1 text-zinc-400">
              <li><span className="text-zinc-300">MercadoPago:</span> processamento de pagamentos (dados mínimos necessários)</li>
              <li><span className="text-zinc-300">Supabase:</span> armazenamento do banco de dados com criptografia em trânsito e em repouso</li>
              <li><span className="text-zinc-300">Provedor de IA:</span> geração de picks por IA (dados anonimizados de partidas, sem dados pessoais)</li>
            </ul>
          </section>

          <section>
            <h2 className="text-white font-bold text-base mb-3">6. Por quanto tempo guardamos</h2>
            <p className="text-zinc-400">
              Seus dados ficam armazenados enquanto sua conta estiver ativa. Após solicitação de exclusão, apagamos
              seus dados pessoais em até 30 dias, exceto os exigidos por lei (dados financeiros por 5 anos, conforme
              legislação fiscal brasileira).
            </p>
          </section>

          <section>
            <h2 className="text-white font-bold text-base mb-3">7. Seus direitos</h2>
            <p className="text-zinc-400 mb-2">Conforme a LGPD (Lei 13.709/2018), você tem direito a:</p>
            <ul className="list-disc list-inside space-y-1 text-zinc-400">
              <li>Confirmar se tratamos seus dados</li>
              <li>Acessar seus dados</li>
              <li>Corrigir dados incompletos ou desatualizados</li>
              <li>Solicitar a exclusão dos seus dados</li>
              <li>Revogar consentimento quando aplicável</li>
              <li>Portabilidade dos dados</li>
            </ul>
            <p className="mt-3 text-zinc-400">
              Para exercer seus direitos, entre em contato:{' '}
              <span className="text-green-400">pickia.noreply@gmail.com</span>
            </p>
          </section>

          <section>
            <h2 className="text-white font-bold text-base mb-3">8. Cookies</h2>
            <p className="text-zinc-400">
              Usamos apenas cookies de sessão (HttpOnly) essenciais para autenticação. Não usamos cookies de
              rastreamento, publicidade ou analytics de terceiros.
            </p>
          </section>

          <section>
            <h2 className="text-white font-bold text-base mb-3">9. Segurança</h2>
            <p className="text-zinc-400">
              Todos os dados são transmitidos via HTTPS (TLS). Senhas são armazenadas com hash bcrypt. Tokens de
              autenticação são cookies HttpOnly inacessíveis a JavaScript. Dados financeiros são processados
              diretamente pelo MercadoPago e não ficam em nossos servidores.
            </p>
          </section>

          <section>
            <h2 className="text-white font-bold text-base mb-3">10. Contato</h2>
            <p className="text-zinc-400">
              Dúvidas sobre esta política? Fale conosco:{' '}
              <span className="text-green-400">pickia.noreply@gmail.com</span>
            </p>
          </section>

        </div>

        <div className="mt-12 pt-6 border-t border-zinc-800 flex gap-4 text-xs text-zinc-600">
          <Link to="/termos" className="hover:text-zinc-400 transition-colors">Termos de Uso</Link>
          <Link to="/" className="hover:text-zinc-400 transition-colors">Início</Link>
        </div>
      </div>
      {/* Sem Footer estas paginas eram beco sem saida: linkadas do rodape do
          site, sem navbar e com uma unica seta de texto pra sair. */}
      <Footer />
    </div>
  )
}
