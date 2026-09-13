import { useState } from 'react'

/*
 * A RODA DE COR DO AVATAR SÓ USA TOM QUE EXISTE NA PALETA.
 *
 * Ela era oito `-600`, e só dois deles eram token: `pink-600` nem existe no
 * tailwind.config, e os outros caíam no valor padrão do Tailwind, igual nos
 * dois temas. Com `text-ink-1` por cima, a inicial ficava ilegível em metade
 * da roda, e em metades diferentes conforme o tema: no escuro (ink-1 branco)
 * sumia no verde (3,1:1), no laranja (3,9:1) e no teal (3,9:1); no claro
 * (ink-1 quase preto) sumia no roxo (3,9:1) e no índigo (3,2:1).
 *
 * Os `-400` são medidos: a nota da paleta clara em index.css registra que
 * todo preenchimento semântico fica entre 5:1 e 9:1 contra o PRETO, e no tema
 * escuro eles são tons claros, onde preto contrasta ainda mais. Por isso a
 * tinta é `on-fill`, que é preto nos dois temas.
 *
 * Verde e vermelho ficam de fora de propósito: neste site verde é GREEN e
 * vermelho é RED. Sortear a cor de "ganhou" para o avatar de quem tem a
 * inicial certa seria dar significado a um hash.
 */
function nameColor(name: string): string {
  const colors = [
    'bg-blue-400', 'bg-purple-400', 'bg-orange-400', 'bg-teal-400',
    'bg-rose-400', 'bg-cyan-400',   'bg-amber-400',  'bg-emerald-400',
  ]
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return colors[Math.abs(hash) % colors.length]
}

interface AvatarProps {
  name: string
  imageUrl?: string | null
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const SIZE = {
  sm: 'w-7 h-7 text-xs',
  md: 'w-9 h-9 text-sm',
  lg: 'w-16 h-16 text-xl',
}

const SIZE_PX = {
  sm: 28,
  md: 36,
  lg: 64,
}

/* O ARQUIVO ESTATICO SOME A CADA DEPLOY, E O BANCO NAO (2026-09-04).
 *
 * `avatar_url` aponta pra `/static/avatars/<id>.<ext>`, gravado no disco do
 * container -- e container do Railway e' efemero: todo deploy sobe um novo e
 * leva os arquivos junto. O sintoma era todo mundo perder a foto e voltar pro
 * circulo de iniciais sempre que o site atualizava.
 *
 * Agora a foto tambem vive no banco, e esta funcao e' a segunda tentativa: o
 * 404 do arquivo estatico cai em `/api/auth/avatar/<id>`, que serve do banco E
 * reescreve o arquivo de passagem. Ou seja, o primeiro visitante depois do
 * deploy paga uma consulta e restaura o cache pra todos os outros.
 *
 * So' o proprio `<id>` do caminho e' reaproveitado: nada de texto de fora entra
 * na URL nova. */
function rotaDoBanco(imageUrl: string): string | null {
  const m = imageUrl.match(/\/static\/avatars\/(\d+)\.[a-z]+$/i)
  return m ? `/api/auth/avatar/${m[1]}` : null
}

export default function Avatar({ name, imageUrl, size = 'md', className = '' }: AvatarProps) {
  /* 0 = a URL que veio; 1 = a rota do banco; 2 = desistiu, mostra as iniciais.
     Um contador e nao um booleano porque sao DUAS tentativas, e um `onError`
     que so' liga uma flag nunca chega na segunda. */
  const [tentativa, setTentativa] = useState(0)

  /* NOME AUSENTE NÃO PODE DERRUBAR A PÁGINA.
   *
   * `name` é obrigatório no tipo, mas `PickSocial` passa `c.user_name` vindo da
   * API, e comentário de conta apagada chega sem nome. Um `undefined.split`
   * aqui estoura no render e leva a TELA INTEIRA para o "Algo deu errado" --
   * uma lista de comentários derrubando a página de picks por causa de um
   * campo vazio.
   *
   * Sem nome, mostra o círculo sem iniciais: é feio e é honesto, e o resto da
   * tela continua de pé. */
  const nome = typeof name === 'string' ? name : ''

  const initials = nome
    .split(' ')
    .slice(0, 2)
    .map(w => w[0]?.toUpperCase() ?? '')
    .join('')

  // URL relativa funciona tanto em dev (proxy Vite /static -> 8000) quanto em prod (mesmo domínio)
  const doBanco = imageUrl ? rotaDoBanco(imageUrl) : null
  const src = !imageUrl || tentativa >= 2 ? null
            : tentativa === 0 ? imageUrl
            : doBanco

  if (src) {
    return (
      <img
        src={src}
        alt={nome}
        width={SIZE_PX[size]}
        height={SIZE_PX[size]}
        className={`${SIZE[size]} rounded-full object-cover shrink-0 ${className}`}
        /* Sem rota do banco (avatar do Google, por exemplo) a primeira falha ja'
           vai direto pras iniciais · nao ha' segunda fonte pra tentar. */
        onError={() => setTentativa(t => (t === 0 && doBanco ? 1 : 2))}
      />
    )
  }

  return (
    <div className={`${SIZE[size]} ${nameColor(nome)} rounded-full flex items-center justify-center font-black text-on-fill shrink-0 select-none ${className}`}>
      {initials}
    </div>
  )
}
