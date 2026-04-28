import { useEffect, useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'

type YearRecord = {
  year: number
  gdd: number
  heat_stress_days: number
  frost_days: number
  precip_winter: number
  severity_score: number
  brix_cab: number | null
  brix_pn: number | null
  brix_chard: number | null
  tons_cab: number | null
  tons_pn: number | null
  tons_chard: number | null
}

type Enriched = YearRecord & Record<string, number>

const TREND_KEYS: (keyof YearRecord)[] = [
  'gdd', 'heat_stress_days', 'precip_winter',
  'brix_cab', 'brix_pn', 'brix_chard',
  'tons_cab', 'tons_pn', 'tons_chard',
]

function addTrends(data: YearRecord[]): Enriched[] {
  const result: Enriched[] = data.map(d => ({ ...d } as Enriched))
  for (const key of TREND_KEYS) {
    const pts = data
      .map((d, i) => ({ x: i, y: d[key] as number | null }))
      .filter((p): p is { x: number; y: number } => p.y != null)
    if (pts.length < 2) continue
    const n = pts.length
    const mx = pts.reduce((s, p) => s + p.x, 0) / n
    const my = pts.reduce((s, p) => s + p.y, 0) / n
    const num = pts.reduce((s, p) => s + (p.x - mx) * (p.y - my), 0)
    const den = pts.reduce((s, p) => s + (p.x - mx) ** 2, 0)
    const slope = num / den
    const intercept = my - slope * mx
    result.forEach((d, i) => { d[`trend_${String(key)}`] = slope * i + intercept })
  }
  return result
}

const WINE = '#7a2f3b'
const WINE_LIGHT = '#9b3f4e'
const MUTED_BLUE = '#5b7fa6'

export default function TrendsView() {
  const [data, setData] = useState<YearRecord[] | null>(null)
  const [loadingData, setLoadingData] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/trends')
      .then(r => r.json())
      .then(d => { setData(d.years); setLoadingData(false) })
      .catch(() => { setError('Failed to load trend data.'); setLoadingData(false) })
  }, [])

  const enriched = useMemo(() => data ? addTrends(data) : null, [data])

  if (loadingData) {
    return (
      <main className="flex-1 flex items-center justify-center">
        <p className="text-muted text-sm">Loading 34-year record…</p>
      </main>
    )
  }

  if (error || !enriched) {
    return (
      <main className="flex-1 flex items-center justify-center">
        <p className="text-red-600 text-sm">{error ?? 'No data available.'}</p>
      </main>
    )
  }

  return (
    <main className="flex-1 w-full max-w-4xl mx-auto px-4 py-10 space-y-6">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-slate tracking-tight">Climate Trends</h1>
        <p className="mt-2 text-muted text-sm max-w-lg mx-auto">
          34 years of Napa Valley climate and harvest data, 1991–2024.
        </p>
      </div>

      {/* Narrative */}
      <div className="bg-white rounded-2xl border border-rose-mist/60 shadow-sm px-8 py-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted mb-3">
          Climate Overview
        </p>
        <p className="text-slate text-sm leading-relaxed">Over the past 34 years, Napa Valley's climate has been shifting in ways that are impossible to ignore: growing degree days have climbed by roughly 141 units from the early period to the late period — an average gain of 4.6 degree-days per year — meaning vines are accumulating significantly more heat across each season. That warming trajectory is reinforcing itself through more frequent heat stress days and, strikingly, through the grapes themselves, as Cabernet Sauvignon's harvest Brix has crept up about 0.077 degrees per year, translating to noticeably riper, higher-sugar fruit than growers were picking in the early 1990s. At the same time, winter precipitation has dropped by more than 100 millimeters on average between the early and late portions of the record — a loss of roughly 12% — and drought severity has trended steadily worse, tightening the water budget that vines depend on during the critical growing season. Together, these patterns paint a picture of a valley that is getting hotter, drier, and more prone to moisture stress, compressing the already-narrow windows for achieving balanced ripeness before sugar levels race ahead of flavor and acidity. For growers, this means irrigation management, canopy architecture, and even variety selection are no longer optional refinements — they are front-line adaptations to a climate</p>
      </div>

      {/* Climate charts */}
      <SectionCard title="Heat Accumulation (GDD)">
        <ChartWrap>
          <LineChart data={enriched}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
            <XAxis dataKey="year" tick={tickStyle} />
            <YAxis tick={tickStyle} width={55} domain={tightDomain} />
            <Tooltip contentStyle={tooltipStyle} content={<FilteredTooltip />} />
            <Line type="monotone" dataKey="gdd" name="GDD" stroke={WINE} dot={false} strokeWidth={2} />
            <Line type="monotone" dataKey="trend_gdd" name="Trend" stroke={WINE} dot={false} strokeWidth={1.5} strokeDasharray="5 3" strokeOpacity={0.5} legendType="none" />
          </LineChart>
        </ChartWrap>
      </SectionCard>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <SectionCard title="Heat Stress Days (>35°C)">
          <ChartWrap height={200}>
            <LineChart data={enriched}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
              <XAxis dataKey="year" tick={tickStyle} />
              <YAxis tick={tickStyle} width={35} domain={tightDomain} />
              <Tooltip contentStyle={tooltipStyle} content={<FilteredTooltip />} />
              <Line type="monotone" dataKey="heat_stress_days" name="Days" stroke={WINE} dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="trend_heat_stress_days" name="Trend" stroke={WINE} dot={false} strokeWidth={1.5} strokeDasharray="5 3" strokeOpacity={0.5} legendType="none" />
            </LineChart>
          </ChartWrap>
        </SectionCard>

        <SectionCard title="Winter Precipitation (mm)">
          <ChartWrap height={200}>
            <LineChart data={enriched}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
              <XAxis dataKey="year" tick={tickStyle} />
              <YAxis tick={tickStyle} width={45} domain={tightDomain} />
              <Tooltip contentStyle={tooltipStyle} content={<FilteredTooltip />} />
              <Line type="monotone" dataKey="precip_winter" name="mm" stroke={MUTED_BLUE} dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="trend_precip_winter" name="Trend" stroke={MUTED_BLUE} dot={false} strokeWidth={1.5} strokeDasharray="5 3" strokeOpacity={0.5} legendType="none" />
            </LineChart>
          </ChartWrap>
        </SectionCard>
      </div>

      {/* Brix */}
      <SectionCard title="Harvest Brix by Variety">
        <ChartWrap>
          <LineChart data={enriched}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
            <XAxis dataKey="year" tick={tickStyle} />
            <YAxis tick={tickStyle} width={40} domain={tightDomain} />
            <Tooltip contentStyle={tooltipStyle} content={<FilteredTooltip />} />
            <Legend wrapperStyle={{ fontSize: '11px' }} />
            <Line type="monotone" dataKey="brix_cab" name="Cab Sauv" stroke={WINE} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="trend_brix_cab" name="Trend" stroke={WINE} dot={false} strokeWidth={1.5} strokeDasharray="5 3" strokeOpacity={0.5} legendType="none" />
            <Line type="monotone" dataKey="brix_pn" name="Pinot Noir" stroke={WINE_LIGHT} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="trend_brix_pn" name="Trend" stroke={WINE_LIGHT} dot={false} strokeWidth={1.5} strokeDasharray="5 3" strokeOpacity={0.5} legendType="none" />
            <Line type="monotone" dataKey="brix_chard" name="Chardonnay" stroke={MUTED_BLUE} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="trend_brix_chard" name="Trend" stroke={MUTED_BLUE} dot={false} strokeWidth={1.5} strokeDasharray="5 3" strokeOpacity={0.5} legendType="none" />
          </LineChart>
        </ChartWrap>
      </SectionCard>

      {/* Tonnage */}
      <SectionCard title="Crushed Tonnage by Variety">
        <ChartWrap>
          <LineChart data={enriched}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
            <XAxis dataKey="year" tick={tickStyle} />
            <YAxis tick={tickStyle} width={65} domain={tightDomain} tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)} />
            <Tooltip contentStyle={tooltipStyle} content={<FilteredTooltip formatter={(v: number) => v.toLocaleString()} />} />
            <Legend wrapperStyle={{ fontSize: '11px' }} />
            <Line type="monotone" dataKey="tons_cab" name="Cab Sauv" stroke={WINE} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="trend_tons_cab" name="Trend" stroke={WINE} dot={false} strokeWidth={1.5} strokeDasharray="5 3" strokeOpacity={0.5} legendType="none" />
            <Line type="monotone" dataKey="tons_pn" name="Pinot Noir" stroke={WINE_LIGHT} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="trend_tons_pn" name="Trend" stroke={WINE_LIGHT} dot={false} strokeWidth={1.5} strokeDasharray="5 3" strokeOpacity={0.5} legendType="none" />
            <Line type="monotone" dataKey="tons_chard" name="Chardonnay" stroke={MUTED_BLUE} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="trend_tons_chard" name="Trend" stroke={MUTED_BLUE} dot={false} strokeWidth={1.5} strokeDasharray="5 3" strokeOpacity={0.5} legendType="none" />
          </LineChart>
        </ChartWrap>
      </SectionCard>
    </main>
  )
}

type TooltipPayloadItem = {
  name: string
  value: number
  color: string
  dataKey: string
}

type TooltipProps = {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: string | number
  formatter?: (v: number) => string
}

function FilteredTooltip({ active, payload, label, formatter }: TooltipProps) {
  if (!active || !payload?.length) return null
  const visible = payload.filter(p => !String(p.dataKey).startsWith('trend_'))
  if (!visible.length) return null
  return (
    <div style={tooltipStyle} className="px-3 py-2 border rounded-lg shadow-sm">
      <p className="text-xs font-semibold text-muted mb-1">{label}</p>
      {visible.map(p => (
        <p key={p.dataKey} className="text-xs" style={{ color: p.color }}>
          {p.name}: {formatter ? formatter(p.value) : p.value}
        </p>
      ))}
    </div>
  )
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-2xl border border-rose-mist/60 shadow-sm px-6 py-5">
      <p className="text-xs font-semibold uppercase tracking-widest text-muted mb-4">{title}</p>
      {children}
    </div>
  )
}

function ChartWrap({ height = 260, children }: { height?: number; children: React.ReactNode }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      {children as React.ReactElement}
    </ResponsiveContainer>
  )
}

const tightDomain = [
  (min: number) => Math.round(min * 0.95),
  (max: number) => Math.round(max * 1.05),
]

const tickStyle = { fontSize: 11, fill: '#8c7375' }
const tooltipStyle = {
  fontSize: 12,
  borderColor: '#f3e8ea',
  borderRadius: 8,
  backgroundColor: '#faf9f6',
}
