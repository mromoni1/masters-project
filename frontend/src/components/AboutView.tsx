type Props = {
  onNavigate: (tab: 'advisory' | 'chat') => void
}

export default function AboutView({ onNavigate }: Props) {
  return (
    <main className="flex-1 w-full max-w-3xl mx-auto px-4 py-12 space-y-8">

      {/* hero */}
      <div className="flex flex-col items-center text-center gap-4">
        <div className="flex items-center justify-center w-20 h-20 rounded-full bg-wine shadow-md">
          <GrapeIcon />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-slate tracking-tight">Napa Vine Advisor</h1>
          <p className="mt-1 text-muted text-sm tracking-widest uppercase">Climate-Informed Decisions</p>
        </div>
      </div>

      {/* about */}
      <Section title="About">
        <p className="text-slate text-sm leading-relaxed">
          Napa Vine Advisor is a climate-informed decision support tool built for small,
          independent Napa Valley vintners. It translates 34 years of publicly available
          climate and agricultural data into plain-language harvest advisories. This tool gives
          growers access to the kind of analytics that large operations take for granted.
        </p>
        <p className="text-slate text-sm leading-relaxed mt-3">
          Select a variety and season year in the Historical Explorer to compare the model's
          blind forecast against the actual CDFA Grape Crush Report outcome, alongside
          a climate-driven retrospective written by Claude. Or ask Winnie any question
          about the 34-year Napa Valley record.
        </p>
      </Section>

      {/* data */}
      <Section title="Data & Methods">
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <DataItem label="Varieties modeled">
            Cabernet Sauvignon, Pinot Noir, Chardonnay
          </DataItem>
          <DataItem label="Time period">
            1991–2024 &mdash; 34 growing seasons
          </DataItem>
          <DataItem label="Climate source">
            PRISM daily grids (GDD, heat stress, frost days, veraison temps, winter precip)
          </DataItem>
          <DataItem label="Yield source">
            CDFA Grape Crush Report &mdash; district-level Brix and crushed tonnage
          </DataItem>
          <DataItem label="Water data">
            CIMIS seasonal ETo &amp; DWR water-year drought classifications
          </DataItem>
          <DataItem label="Soil data">
            SSURGO available water capacity, drainage class, and texture
          </DataItem>
          <DataItem label="Prediction model">
            Gradient boosting (LightGBM), walk-forward cross-validation,
            evaluated against four historical baselines
          </DataItem>
          <DataItem label="Retrospective analysis">
            Claude claude-sonnet-4-6 — explains what drove the season, how closely
            the model tracked reality, and what makes the vintage distinctive
          </DataItem>
        </dl>
      </Section>

      {/* navigation */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-2">
        <NavCard
          title="Historical Explorer"
          description="Compare model predictions against real CDFA harvest outcomes for any season from 1992–2024."
          onClick={() => onNavigate('advisory')}
          icon={<AdvisoryIcon />}
        />
        <NavCard
          title="Ask the Data"
          description="Ask Winnie anything about 34 years of Napa Valley climate and harvest records."
          onClick={() => onNavigate('chat')}
          icon={<ChatIcon />}
        />
      </div>
    </main>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-2xl border border-rose-mist/60 shadow-sm px-8 py-6">
      <h2 className="text-base font-bold text-wine uppercase tracking-widest mb-4">{title}</h2>
      {children}
    </div>
  )
}

function DataItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-semibold text-muted uppercase tracking-wide mb-0.5">{label}</dt>
      <dd className="text-sm text-slate leading-snug">{children}</dd>
    </div>
  )
}

function NavCard({
  title, description, onClick, icon,
}: {
  title: string
  description: string
  onClick: () => void
  icon: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className="group flex flex-col gap-3 text-left bg-white rounded-2xl border border-rose-mist/60 shadow-sm px-6 py-5 hover:border-wine/50 hover:shadow-md transition"
    >
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-full bg-rose-mist text-wine group-hover:bg-wine group-hover:text-cream transition">
          {icon}
        </div>
        <span className="font-bold text-slate text-sm">{title}</span>
      </div>
      <p className="text-sm text-muted leading-snug">{description}</p>
      <span className="text-xs font-semibold text-wine group-hover:underline">
        Open &rarr;
      </span>
    </button>
  )
}

function GrapeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-10 h-10 text-cream" aria-hidden="true">
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

function AdvisoryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4" aria-hidden="true">
      <path d="M9 17H5a2 2 0 0 0-2 2v0a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v0a2 2 0 0 0-2-2h-4" />
      <path d="M12 3v14" />
      <path d="M8 7l4-4 4 4" />
    </svg>
  )
}

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4" aria-hidden="true">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}
