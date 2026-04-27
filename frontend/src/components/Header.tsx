type Tab = 'about' | 'advisory' | 'chat'

type Props = {
  activeTab: Tab
  onTabChange: (tab: Tab) => void
}

export default function Header({ activeTab, onTabChange }: Props) {
  return (
    <header className="bg-white border-b border-rose-mist/60 shadow-sm">
      <div
        className="flex items-center gap-3 px-6 py-4 cursor-pointer w-fit"
        onClick={() => onTabChange('about')}
      >
        <div className="flex items-center justify-center w-9 h-9 rounded-full bg-wine shrink-0">
          <GrapeIcon />
        </div>
        <span className="text-lg font-bold tracking-tight text-wine">
          Napa Vine Advisor
        </span>
      </div>

      <nav className="flex px-6 gap-1">
        <TabButton label="About" active={activeTab === 'about'} onClick={() => onTabChange('about')} />
        <TabButton label="Harvest Advisory" active={activeTab === 'advisory'} onClick={() => onTabChange('advisory')} />
        <TabButton label="Ask the Data" active={activeTab === 'chat'} onClick={() => onTabChange('chat')} />
      </nav>
    </header>
  )
}

function TabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
        active
          ? 'border-wine text-wine'
          : 'border-transparent text-muted hover:text-slate hover:border-rose-mist'
      }`}
    >
      {label}
    </button>
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
      <path d="M12 2 Q14 4 13 6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
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
