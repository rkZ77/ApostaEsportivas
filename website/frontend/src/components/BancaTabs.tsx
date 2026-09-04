import { useLocation, useNavigate } from 'react-router-dom'

/*
 * Sub-navegação da Minha Banca.
 *
 * POR QUE ABAS, E NÃO OS BOTÕES QUE ESTAVAM AQUI
 * ----------------------------------------------
 * As cinco telas da banca eram alcançadas de três jeitos diferentes: dois
 * botões na barra do topo (Ajustar, Sacar), um card com botão no meio da
 * página (Ver alavancagem) e um link solto (Fechamentos). Três formas pro
 * mesmo tipo de destino, e nenhuma delas dizia QUANTAS telas existem nem em
 * qual você está.
 *
 * Aba resolve as duas coisas de uma vez: a lista inteira fica visível e a atual
 * fica marcada. É o mesmo desenho de /resultados, que já era o padrão do site
 * para "uma seção com várias leituras".
 *
 * O AVISO DA ALAVANCAGEM CONTINUA onde estava, e não vira só a aba: ele diz o
 * que a alavancagem NÃO é (não está nesta banca enquanto o caminho roda), e
 * essa frase precisa aparecer junto do número que ela não compõe. O que sai
 * dali é o botão, que agora é redundante.
 */
const ABAS: [string, string][] = [
  ['/banca',              'Visão geral'],
  ['/banca/alavancagem',  'Alavancagem'],
  ['/banca/fechamentos',  'Fechamentos'],
  ['/banca/ajustar',      'Ajustar'],
  ['/banca/saque',        'Sacar'],
]

export default function BancaTabs() {
  const navigate = useNavigate()
  const { pathname } = useLocation()

  return (
    <div className="flex border-b border-line mb-6 overflow-x-auto">
      {ABAS.map(([to, label]) => (
        <button
          key={to}
          onClick={() => { if (to !== pathname) navigate(to) }}
          className={`tab px-5 py-3 text-sm font-semibold whitespace-nowrap ${
            pathname === to ? 'tab-active' : ''
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
