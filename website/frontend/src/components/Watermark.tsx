export default function Watermark({ email }: { email: string }) {
  const cols = 3
  const rows = 9

  return (
    <div
      className="fixed inset-0 pointer-events-none select-none overflow-hidden"
      style={{ zIndex: 9 }}
      aria-hidden="true"
    >
      <div
        style={{
          position: 'absolute',
          inset: '-60%',
          display: 'grid',
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gridTemplateRows: `repeat(${rows}, 1fr)`,
          transform: 'rotate(-28deg)',
        }}
      >
        {Array.from({ length: cols * rows }).map((_, i) => (
          <div key={i} className="flex flex-col items-center justify-center gap-1 opacity-[0.055]">
            <img
              src="/logo.png"
              alt=""
              width={28}
              height={28}
              className="object-contain"
              style={{ filter: 'brightness(0) invert(1)' }}
            />
            <span className="text-white text-[10px] font-semibold whitespace-nowrap tracking-wide">
              {email}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
