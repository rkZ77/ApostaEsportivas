const WA_LINK =
  'https://wa.me/5517992323916?text=Ol%C3%A1!%20Preciso%20de%20suporte%20no%20Pick%20IA.'

export default function WhatsAppButton() {
  return (
    <a
      href={WA_LINK}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Suporte via WhatsApp"
      // bottom usa safe-area-inset-bottom para não ficar atrás da home indicator do iPhone
      style={{ bottom: 'calc(1.25rem + env(safe-area-inset-bottom))' }}
      className="fixed right-4 z-50 flex items-center gap-2 bg-[#25D366] hover:bg-[#20ba58] active:bg-[#1aa34a] text-white font-bold shadow-lg shadow-black/40 transition-all hover:scale-105 active:scale-95
        rounded-full px-3 py-3 sm:px-4 sm:py-3 sm:rounded-full"
    >
      <svg viewBox="0 0 24 24" className="w-6 h-6 shrink-0 fill-white">
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
        <path d="M12 0C5.373 0 0 5.373 0 12c0 2.124.554 4.118 1.528 5.849L.057 23.428a.5.5 0 0 0 .609.61l5.66-1.485A11.945 11.945 0 0 0 12 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.882a9.875 9.875 0 0 1-5.031-1.374l-.36-.214-3.733.979.997-3.645-.235-.374A9.855 9.855 0 0 1 2.118 12C2.118 6.54 6.54 2.118 12 2.118S21.882 6.54 21.882 12 17.46 21.882 12 21.882z"/>
      </svg>
      {/* Texto só aparece em telas maiores que mobile */}
      <span className="hidden sm:inline text-sm">Suporte</span>
    </a>
  )
}
