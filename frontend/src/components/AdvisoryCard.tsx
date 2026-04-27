export type AdvisoryResponse = {
  variety: string
  year: number
  brix_predicted: number
  brix_range: [number, number]
  tonnage_predicted: number
  tonnage_range: [number, number]
  harvest_window: string
  advisory_text: string
}

type Props = {
  data: AdvisoryResponse
}

export default function AdvisoryCard({ data }: Props) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-rose-mist/60 overflow-hidden">
      {/* header band */}
      <div className="bg-wine px-8 py-5">
        <p className="text-rose-mist/80 text-xs font-semibold uppercase tracking-widest mb-0.5">
          {data.year} Harvest Advisory
        </p>
        <h3 className="text-cream text-xl font-bold">{data.variety}</h3>
      </div>

      {/* metrics row */}
      <div className="grid grid-cols-3 divide-x divide-rose-mist/60 border-b border-rose-mist/60">
        <Metric
          label="Projected Brix"
          value={data.brix_predicted.toFixed(1)}
          range={`${data.brix_range[0].toFixed(1)}–${data.brix_range[1].toFixed(1)}`}
          unit="°Bx"
        />
        <Metric
          label="Projected Tonnage"
          value={formatTons(data.tonnage_predicted)}
          range={`${formatTons(data.tonnage_range[0])}–${formatTons(data.tonnage_range[1])}`}
          unit="tons"
        />
        <Metric
          label="Harvest Window"
          value={data.harvest_window}
          range=""
          unit=""
        />
      </div>

      {/* advisory text */}
      <div className="px-8 py-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted mb-3">
          Advisory
        </p>
        <p className="text-slate text-base leading-relaxed">{data.advisory_text}</p>
      </div>
    </div>
  )
}

type MetricProps = {
  label: string
  value: string
  range: string
  unit: string
}

function Metric({ label, value, range, unit }: MetricProps) {
  return (
    <div className="px-6 py-5">
      <p className="text-xs font-semibold uppercase tracking-widest text-muted mb-1">{label}</p>
      <p className="text-2xl font-bold text-wine">
        {value}
        {unit && <span className="text-sm font-normal text-muted ml-1">{unit}</span>}
      </p>
      {range && (
        <p className="text-xs text-muted mt-0.5">range {range}</p>
      )}
    </div>
  )
}

function formatTons(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toFixed(0)
}
