export type AdvisoryResponse = {
  variety: string
  year: number
  brix_predicted: number
  brix_range: [number, number]
  tonnage_predicted: number
  tonnage_range: [number, number]
  brix_actual: number
  tonnage_actual: number
  climate: {
    gdd: number
    frost_days: number
    heat_stress_days: number
    tmax_veraison: number
    precip_winter: number
    severity_score: number
  }
  analysis: string
}

type Props = {
  data: AdvisoryResponse
}

export default function AdvisoryCard({ data }: Props) {
  const brixInRange = data.brix_actual >= data.brix_range[0] && data.brix_actual <= data.brix_range[1]
  const tonsInRange = data.tonnage_actual >= data.tonnage_range[0] && data.tonnage_actual <= data.tonnage_range[1]
  const brixDelta = round1(data.brix_actual - data.brix_predicted)
  const tonsDelta = Math.round(data.tonnage_actual - data.tonnage_predicted)

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-rose-mist/60 overflow-hidden">

      {/* header */}
      <div className="bg-wine px-8 py-5">
        <p className="text-rose-mist/80 text-xs font-semibold uppercase tracking-widest mb-0.5">
          Historical Season Analysis
        </p>
        <h3 className="text-cream text-xl font-bold">{data.variety} · {data.year}</h3>
      </div>

      {/* predicted vs actual */}
      <div className="grid grid-cols-2 divide-x divide-rose-mist/60 border-b border-rose-mist/60">
        <ComparisonCol
          label="Model Predicted"
          brix={data.brix_predicted}
          brixSub={`range ${data.brix_range[0]}–${data.brix_range[1]}`}
          tons={data.tonnage_predicted}
          tonsSub={`range ${formatTons(data.tonnage_range[0])}–${formatTons(data.tonnage_range[1])}`}
          muted
        />
        <ComparisonCol
          label="Actual Harvest"
          brix={data.brix_actual}
          brixSub={brixInRange ? 'within predicted range' : deltaLabel(brixDelta, '°Bx')}
          brixAccent={brixInRange ? 'match' : brixDelta > 0 ? 'high' : 'low'}
          tons={data.tonnage_actual}
          tonsSub={tonsInRange ? 'within predicted range' : deltaLabel(tonsDelta, ' tons')}
          tonsAccent={tonsInRange ? 'match' : tonsDelta > 0 ? 'high' : 'low'}
        />
      </div>

      {/* climate strip */}
      <div className="grid grid-cols-3 divide-x divide-rose-mist/60 border-b border-rose-mist/60 bg-rose-mist/10">
        <ClimStat label="Growing Degree Days" value={data.climate.gdd.toLocaleString()} />
        <ClimStat label="Heat Stress Days" value={String(data.climate.heat_stress_days)} />
        <ClimStat label="Winter Precip" value={`${data.climate.precip_winter.toLocaleString()} mm`} />
      </div>
      <div className="grid grid-cols-3 divide-x divide-rose-mist/60 border-b border-rose-mist/60 bg-rose-mist/10">
        <ClimStat label="Frost Days (Mar–May)" value={String(data.climate.frost_days)} />
        <ClimStat label="Tmax at Veraison" value={`${data.climate.tmax_veraison}°C`} />
        <ClimStat label="Drought Severity" value={`${data.climate.severity_score} / 5`} />
      </div>

      {/* analysis */}
      <div className="px-8 py-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted mb-3">Season Analysis</p>
        <p className="text-slate text-sm leading-relaxed">{data.analysis}</p>
      </div>

    </div>
  )
}

type Accent = 'match' | 'high' | 'low' | undefined

type ComparisonColProps = {
  label: string
  brix: number
  brixSub: string
  brixAccent?: Accent
  tons: number
  tonsSub: string
  tonsAccent?: Accent
  muted?: boolean
}

function ComparisonCol({ label, brix, brixSub, brixAccent, tons, tonsSub, tonsAccent, muted }: ComparisonColProps) {
  return (
    <div className="px-6 py-5 space-y-4">
      <p className="text-xs font-semibold uppercase tracking-widest text-muted">{label}</p>
      <div>
        <p className={`text-2xl font-bold ${muted ? 'text-muted' : 'text-slate'}`}>
          {brix.toFixed(1)}<span className="text-sm font-normal text-muted ml-1">°Bx</span>
        </p>
        <p className={`text-xs mt-0.5 ${accentClass(brixAccent)}`}>{brixSub}</p>
      </div>
      <div>
        <p className={`text-2xl font-bold ${muted ? 'text-muted' : 'text-slate'}`}>
          {formatTons(tons)}<span className="text-sm font-normal text-muted ml-1">tons</span>
        </p>
        <p className={`text-xs mt-0.5 ${accentClass(tonsAccent)}`}>{tonsSub}</p>
      </div>
    </div>
  )
}

function ClimStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-6 py-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted mb-0.5">{label}</p>
      <p className="text-sm font-semibold text-slate">{value}</p>
    </div>
  )
}

function accentClass(accent: Accent): string {
  if (accent === 'match') return 'text-emerald-600'
  if (accent === 'high') return 'text-amber-600'
  if (accent === 'low') return 'text-sky-600'
  return 'text-muted'
}

function deltaLabel(delta: number, unit: string): string {
  const sign = delta > 0 ? '+' : ''
  const val = unit === ' tons' ? Math.abs(delta).toLocaleString() : Math.abs(delta).toFixed(1)
  return `${sign}${delta > 0 ? '+' : '−'}${val}${unit} vs prediction`
}

function formatTons(n: number): string {
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toFixed(0)
}

function round1(n: number): number {
  return Math.round(n * 10) / 10
}
