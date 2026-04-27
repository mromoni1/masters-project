export default function Header() {
  return (
    <header className="flex items-center gap-3 px-6 py-4 bg-white border-b border-rose-mist/60 shadow-sm">
      <div className="flex items-center justify-center w-9 h-9 rounded-full bg-wine shrink-0">
        <GrapeIcon />
      </div>
      <span className="text-lg font-bold tracking-tight text-wine">
        Napa Vine Advisor
      </span>
    </header>
  )
}

function GrapeIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      className="w-5 h-5 text-cream"
      aria-hidden="true"
    >
      {/* stem */}
      <path d="M12 2 Q14 4 13 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      {/* grape cluster circles */}
      <circle cx="10" cy="8"  r="2" />
      <circle cx="14" cy="8"  r="2" />
      <circle cx="8"  cy="12" r="2" />
      <circle cx="12" cy="12" r="2" />
      <circle cx="16" cy="12" r="2" />
      <circle cx="10" cy="16" r="2" />
      <circle cx="14" cy="16" r="2" />
      <circle cx="12" cy="20" r="2" />
    </svg>
  )
}
