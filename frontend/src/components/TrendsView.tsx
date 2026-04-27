import { useEffect, useState } from 'react'
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

const WINE = '#7a2f3b'
const WINE_LIGHT = '#9b3f4e'
const MUTED_BLUE = '#5b7fa6'

export default function TrendsView() {
  const [data, setData] = useState<YearRecord[] | null>(null)
  const [narrative, setNarrative] = useState<string | null>(null)
  const [loadingData, setLoadingData] = useState(true)
  const [loadingNarrative, setLoadingNarrative] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/trends')
      .then(r => r.json())
      .then(d => { setData(d.years); setLoadingData(false) })
      .catch(() => { setError('Failed to load trend data.'); setLoadingData(false) })

    fetch('/api/trends/narrative')
      .then(r => r.json())
      .then(d => { setNarrative(d.narrative); setLoadingNarrative(false) })
      .catch(() => { setLoadingNarrative(false) })
  }, [])

  if (loadingData) {
    return (
      <main className="flex-1 flex items-center justify-center">
        <p className="text-muted text-sm">Loading 34-year record…</p>
      </main>
    )
  }

  if (error || !data) {
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
        {loadingNarrative ? (
          <p className="text-muted text-sm">Generating summary…</p>
        ) : narrative ? (
          <p className="text-slate text-sm leading-relaxed">{narrative}</p>
        ) : (
          <p className="text-muted text-sm">Summary unavailable.</p>
        )}
      </div>

      {/* Climate charts */}
      <SectionCard title="Heat Accumulation">
        <ChartWrap>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
            <XAxis dataKey="year" tick={tickStyle} />
            <YAxis tick={tickStyle} width={55} />
            <Tooltip contentStyle={tooltipStyle} />
            <Line type="monotone" dataKey="gdd" name="GDD" stroke={WINE} dot={false} strokeWidth={2} />
          </LineChart>
        </ChartWrap>
      </SectionCard>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <SectionCard title="Heat Stress Days (>35°C)">
          <ChartWrap height={200}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
              <XAxis dataKey="year" tick={tickStyle} />
              <YAxis tick={tickStyle} width={35} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="heat_stress_days" name="Days" stroke={WINE} dot={false} strokeWidth={2} />
            </LineChart>
          </ChartWrap>
        </SectionCard>

        <SectionCard title="Winter Precipitation (mm)">
          <ChartWrap height={200}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
              <XAxis dataKey="year" tick={tickStyle} />
              <YAxis tick={tickStyle} width={45} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="precip_winter" name="mm" stroke={MUTED_BLUE} dot={false} strokeWidth={2} />
            </LineChart>
          </ChartWrap>
        </SectionCard>
      </div>

      {/* Brix */}
      <SectionCard title="Harvest Brix by Variety">
        <ChartWrap>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
            <XAxis dataKey="year" tick={tickStyle} />
            <YAxis tick={tickStyle} width={40} domain={['auto', 'auto']} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: '11px' }} />
            <Line type="monotone" dataKey="brix_cab" name="Cab Sauv" stroke={WINE} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="brix_pn" name="Pinot Noir" stroke={WINE_LIGHT} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="brix_chard" name="Chardonnay" stroke={MUTED_BLUE} dot={false} strokeWidth={2} connectNulls />
          </LineChart>
        </ChartWrap>
      </SectionCard>

      {/* Tonnage */}
      <SectionCard title="Crushed Tonnage by Variety">
        <ChartWrap>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3e8ea" />
            <XAxis dataKey="year" tick={tickStyle} />
            <YAxis tick={tickStyle} width={65} tickFormatter={(v: number) => v >= 1000 ? `${(v/1000).toFixed(0)}k` : String(v)} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => v.toLocaleString()} />
            <Legend wrapperStyle={{ fontSize: '11px' }} />
            <Line type="monotone" dataKey="tons_cab" name="Cab Sauv" stroke={WINE} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="tons_pn" name="Pinot Noir" stroke={WINE_LIGHT} dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="tons_chard" name="Chardonnay" stroke={MUTED_BLUE} dot={false} strokeWidth={2} connectNulls />
          </LineChart>
        </ChartWrap>
      </SectionCard>
    </main>
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

const tickStyle = { fontSize: 11, fill: '#8c7375' }
const tooltipStyle = {
  fontSize: 12,
  borderColor: '#f3e8ea',
  borderRadius: 8,
  backgroundColor: '#faf9f6',
}
