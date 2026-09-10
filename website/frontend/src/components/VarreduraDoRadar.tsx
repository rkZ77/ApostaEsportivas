import { useState } from 'react'
import { escudoDoTime } from '../lib/aoVivo'

/*
 * O RADAR, DESENHADO COMO RADAR (10/09/2026, pedido do usuário).
 *
 * A seção já se chamava Radar e tinha um ícone pulsando, o que dizia "ligado" e
 * mais nada. Aqui a varredura é a própria figura: o feixe gira, e cada jogo que
 * o motor acompanha aparece como um alvo na tela.
 *
 * O RAIO SIGNIFICA ALGUMA COISA, e é isso que separa isto de enfeite. A janela
 * do motor vai dos 15 aos 80 minutos: jogo que acabou de entrar nela aparece na
 * borda, e vai se aproximando do centro conforme o tempo passa. Quem está perto
 * do meio é quem tem menos jogo pela frente, ou seja, menos espaço para o pick
 * aparecer. O ângulo não codifica nada, e por isso os alvos são distribuídos em
 * volta igualmente: fingir sentido onde não há seria pior que ar.
 *
 * O VERDE É O QUE JÁ VIROU PICK. É a única cor com significado aqui; o resto do
 * desenho é linha fina, para o alvo aceso ser o que a vista pega primeiro.
 *
 * O FEIXE PARA com `prefers-reduced-motion`. A figura continua legível parada ·
 * ela não depende do movimento para dizer onde cada jogo está.
 */

interface Alvo {
  fixture_id: number
  home_team: string | null
  away_team: string | null
  home_team_id: number | null
  away_team_id: number | null
  minuto: number | null
  tem_pick: boolean
  aguardando?: boolean
  /** Minuto que ANDA entre duas varreduras, projetado da última leitura, e se
   *  ele é projeção. Vem calculado de fora porque quem tem o relógio da tela é
   *  o feed (ver `minutoVivo` em LivePicksFeed). */
  minutoVivo?: number | null
  minutoProjetado?: boolean
}

/** Janela em que o motor trabalha · fora dela a partida nem entra no radar. */
const MIN_JANELA = 15
const MAX_JANELA = 90

/** Quantos alvos cabem sem virar sopa de escudo. O resto segue nos cartões. */
const MAX_ALVOS = 8

function Escudo({ id, nome }: { id?: number | null; nome?: string | null }) {
  /* Escudo que não vem NÃO PODE VIRAR QUADRADO VAZIO · o alvo é o jogo, e um
     buraco no lugar do time faz o radar parecer quebrado. Mesma queda dos
     outros escudos do site: a inicial do time. */
  const [falhou, setFalhou] = useState(false)
  const src = escudoDoTime(id ?? undefined)
  if (!src || falhou) {
    return (
      <span className="w-3.5 h-3.5 rounded-full bg-surface-3 border border-line shrink-0
                       flex items-center justify-center text-[7px] font-bold text-ink-4 uppercase">
        {(nome ?? '?').slice(0, 1)}
      </span>
    )
  }
  return <img src={src} alt="" aria-hidden="true" width={14} height={14}
              onError={() => setFalhou(true)}
              className="w-3.5 h-3.5 object-contain shrink-0" />
}

export default function VarreduraDoRadar({ partidas }: { partidas: Alvo[] }) {
  const alvos = partidas.slice(0, MAX_ALVOS)
  if (alvos.length === 0) return null

  return (
    <div className="relative w-full max-w-[210px] mx-auto aspect-square mb-4 select-none">
      {/* Os anéis. Três, e não uma grade: eles dão a noção de distância sem
          prometer uma escala que o desenho não tem. */}
      {[100, 68, 36].map(pct => (
        <div key={pct} aria-hidden="true"
             className="absolute rounded-full border border-line"
             style={{
               width: `${pct}%`, height: `${pct}%`,
               left: `${(100 - pct) / 2}%`, top: `${(100 - pct) / 2}%`,
             }} />
      ))}
      {/* As cruzetas, bem apagadas · são o que faz o círculo parecer um
          instrumento e não um donut. */}
      <div aria-hidden="true" className="absolute inset-x-0 top-1/2 h-px bg-line/60" />
      <div aria-hidden="true" className="absolute inset-y-0 left-1/2 w-px bg-line/60" />

      {/* O FEIXE. Um setor de cone que gira · o rastro é o gradiente que se
          apaga atrás dele, igual ao de um sonar. */}
      <div
        aria-hidden="true"
        className="absolute inset-0 rounded-full motion-safe:animate-varredura
                   motion-reduce:hidden"
        style={{
          background:
            'conic-gradient(from 0deg, rgb(var(--accent) / 0.28) 0deg, ' +
            'rgb(var(--accent) / 0.10) 26deg, transparent 60deg, transparent 360deg)',
          maskImage: 'radial-gradient(circle, #000 0 99%, transparent 100%)',
          WebkitMaskImage: 'radial-gradient(circle, #000 0 99%, transparent 100%)',
        }}
      />

      {/* O centro. */}
      <div aria-hidden="true"
           className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2
                      w-1.5 h-1.5 rounded-full bg-accent/70" />

      {alvos.map((p, i) => {
        /* Ângulo: distribuído em volta, começando no topo. Um giro inteiro
           dividido pelo número de alvos, com meio passo de defasagem para dois
           jogos nunca caírem exatamente sobre uma cruzeta. */
        const ang = (i / alvos.length) * 2 * Math.PI - Math.PI / 2 + Math.PI / alvos.length
        /* Raio: quem tem mais jogo pela frente fica mais longe do centro. Jogo
           que o motor ainda não leu entra na borda, que é onde ele de fato
           está: acabou de começar. */
        const minuto = p.minutoVivo ?? p.minuto
        const projetado = !!p.minutoProjetado
        const paraORaio = p.aguardando ? MIN_JANELA : (minuto ?? MIN_JANELA)
        const andado = Math.min(1, Math.max(0,
          (paraORaio - MIN_JANELA) / (MAX_JANELA - MIN_JANELA)))
        const raio = 44 - andado * 26   // 44% da caixa na borda, 18% no miolo
        const x = 50 + Math.cos(ang) * raio
        const y = 50 + Math.sin(ang) * raio
        return (
          <div
            key={p.fixture_id}
            title={`${p.home_team ?? 'Time'} x ${p.away_team ?? 'Time'}`
                   + (minuto != null ? `, ${minuto}'` : '')
                   + (p.tem_pick ? ' · já virou pick' : '')}
            className={`absolute -translate-x-1/2 -translate-y-1/2 flex items-center gap-0.5
                        transition-[left,top] duration-1000 ease-linear
                        rounded-full border px-1.5 py-1 backdrop-blur-[1px] ${
              p.tem_pick
                ? 'border-accent/60 bg-accent/15 shadow-[0_0_10px_rgba(0,204,0,0.25)]'
                : 'border-line-strong bg-surface-1/90'}`}
            style={{ left: `${x}%`, top: `${y}%` }}
          >
            {/* O ALVO QUE JÁ VIROU PICK PISCA · num radar, o que foi
                encontrado é o que chama. O `motion-safe` respeita quem pediu
                menos animação. */}
            {p.tem_pick && (
              <span aria-hidden="true"
                    className="absolute inset-0 rounded-full border border-accent/50
                               motion-safe:animate-ping" />
            )}
            <Escudo id={p.home_team_id} nome={p.home_team} />
            <Escudo id={p.away_team_id} nome={p.away_team} />
            {minuto != null && (
              /* O MINUTO ANDA SOZINHO entre duas varreduras · o `~` avisa
                 quando ele é projeção da última leitura, e não leitura nova. */
              <span className="font-mono text-[9px] font-bold text-ink-3 tabular-nums ml-0.5">
                {projetado ? '~' : ''}{minuto}&apos;
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
