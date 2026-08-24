import { ReactNode } from 'react'

function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
}

export function P({ children }: { children: ReactNode }) {
  return <p className="text-ink-2 text-[15px] leading-relaxed mb-5">{children}</p>
}

export function H2({ children }: { children: string }) {
  const id = slugify(children)
  return (
    <h2 id={id} className="text-ink-1 text-xl sm:text-2xl font-bold mt-10 mb-4 scroll-mt-24">
      {children}
    </h2>
  )
}

export function H3({ children }: { children: string }) {
  const id = slugify(children)
  return (
    <h3 id={id} className="text-ink-1 text-lg font-bold mt-6 mb-3 scroll-mt-24">
      {children}
    </h3>
  )
}

export function UL({ children }: { children: ReactNode }) {
  return <ul className="space-y-2 mb-5 pl-5 list-disc list-outside marker:text-accent-ink">{children}</ul>
}

export function OL({ children }: { children: ReactNode }) {
  return (
    <ol className="space-y-2 mb-5 pl-5 list-decimal list-outside marker:text-accent-ink marker:font-bold">
      {children}
    </ol>
  )
}

export function LI({ children }: { children: ReactNode }) {
  return <li className="text-ink-2 text-[15px] leading-relaxed">{children}</li>
}

export function Strong({ children }: { children: ReactNode }) {
  return <strong className="text-ink-1 font-bold">{children}</strong>
}

export function Quote({ children }: { children: ReactNode }) {
  return (
    <blockquote className="border-l-2 border-green-500 pl-4 py-1 my-6 text-ink-2 italic text-sm">
      {children}
    </blockquote>
  )
}

export function Callout({ children }: { children: ReactNode }) {
  return (
    <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-5 my-6">
      <p className="text-ink-2 text-sm leading-relaxed">{children}</p>
    </div>
  )
}
