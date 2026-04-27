import { useState } from 'react'

const VARIETIES = ['Cabernet Sauvignon', 'Pinot Noir', 'Chardonnay']
const MAX_YEAR = 2024
const BASE_YEARS = Array.from({ length: MAX_YEAR - 1991 }, (_, i) => MAX_YEAR - i)
const CLIMATE_YEARS = Array.from({ length: MAX_YEAR - 1990 }, (_, i) => MAX_YEAR - i)

type ClimateDiffRow = {
  label: string
  base: number
  counterfactual: number
  delta: number
}

type CFResult = {
  variety: string
  base_year: number
  climate_year: number
  base: { brix: number; tons: number }
  counterfactual: { brix: number; tons: number }
  climate_diff: ClimateDiffRow[]
  analysis: string
}

type ApiError = { detail: string }

export default function CounterfactualView() {
  const [variety, setVariety] = useState('Cabernet Sauvignon')
  const [baseYear, setBaseYear] = useState(2010)
  const [climateYear, setClimateYear] = useState(2021)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<CFResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch('/api/counterfactual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ variety, base_year: baseYear, climate_year: climateYear }),
      })
      if (!res.ok) {
        const err: ApiError = await res.json()
        throw new Error(err.detail ?? `Server error ${res.status}`)
      }
      setResult(await res.json())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'An unexpected error occurred.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="flex-1 w-full max-w-3xl mx-auto px-4 py-10 space-y-6">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-slate tracking-tight">Counterfactual Explorer</h1>
        <p className="mt-2 text-muted text-sm max-w-md mx-auto">
          Ask the model: what would a given variety and season have looked like
          with a different year's climate?
        </p>
      </div>

      {/* Form */}
      <div className="bg-white rounded-2xl shadow-sm border border-rose-mist/60 p-8">
        <div className="flex items-center gap-3 mb-6">
          <div className="flex items-center justify-center w-10 h-10 rounded-full bg-rose-mist shrink-0">
            <SwapIcon />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate leading-tight">Configure Scenario</h2>
            <p className="text-sm text-muted">
              Choose a variety, a base season, and the climate year to swap in.
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            <label className="block">
              <span className="text-sm font-semibold text-slate mb-1.5 block">Grape Variety</span>
              <select
                value={variety}
                onChange={e => setVariety(e.target.value)}
                className="w-full rounded-lg border border-rose-mist bg-cream px-4 py-2.5 text-slate text-sm focus:outline-none focus:ring-2 focus:ring-wine/40 focus:border-wine transition"
              >
                {VARIETIES.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>

            <label className="block">
              <span className="text-sm font-semibold text-slate mb-1.5 block">Base Season</span>
              <select
                value={baseYear}
                onChange={e => setBaseYear(Number(e.target.value))}
                className="w-full rounded-lg border border-rose-mist bg-cream px-4 py-2.5 text-slate text-sm focus:outline-none focus:ring-2 focus:ring-wine/40 focus:border-wine transition"
              >
                {BASE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </label>

            <label className="block">
              <span className="text-sm font-semibold text-slate mb-1.5 block">Climate Year</span>
              <select
                value={climateYear}
                onChange={e => setClimateYear(Number(e.target.value))}
                className="w-full rounded-lg border border-rose-mist bg-cream px-4 py-2.5 text-slate text-sm focus:outline-none focus:ring-2 focus:ring-wine/40 focus:border-wine transition"
              >
                {CLIMATE_YEARS.filter(y => y !== baseYear).map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </label>
          </div>

          <p className="text-xs text-muted italic">
            "{variety} in {baseYear}, but with {climateYear}'s climate"
          </p>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-wine text-cream font-semibold py-3 text-sm tracking-wide hover:bg-wine-dark active:scale-[0.99] transition disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {loading ? 'Running Scenario…' : 'Run Counterfactual'}
          </button>
        </form>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && <CFResultCard data={result} />}
    </main>
  )
}

function CFResultCard({ data }: { data: CFResult }) {
  const brixDelta = round1(data.counterfactual.brix - data.base.brix)
  const tonsDelta = Math.round(data.counterfactual.tons - data.base.tons)

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-rose-mist/60 overflow-hidden">
      {/* header */}
      <div className="bg-wine px-8 py-5">
        <p className="text-rose-mist/80 text-xs font-semibold uppercase tracking-widest mb-0.5">
          Counterfactual Scenario
        </p>
        <h3 className="text-cream text-xl font-bold">
          {data.variety} · {data.base_year} with {data.climate_year} climate
        </h3>
      </div>

      {/* prediction comparison */}
      <div className="grid grid-cols-2 divide-x divide-rose-mist/60 border-b border-rose-mist/60">
        <PredCol label={`${data.base_year} (actual climate)`} brix={data.base.brix} tons={data.base.tons} muted />
        <PredCol
          label={`With ${data.climate_year} climate`}
          brix={data.counterfactual.brix}
          tons={data.counterfactual.tons}
          brixDelta={brixDelta}
          tonsDelta={tonsDelta}
        />
      </div>

      {/* climate diff table */}
      <div className="border-b border-rose-mist/60">
        <div className="px-8 pt-5 pb-2">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted mb-3">
            Climate Differences ({data.climate_year} vs {data.base_year})
          </p>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-rose-mist/20 text-left">
              <th className="px-8 py-2 text-xs font-semibold text-muted uppercase tracking-wide">Factor</th>
              <th className="px-4 py-2 text-xs font-semibold text-muted uppercase tracking-wide text-right">{data.base_year}</th>
              <th className="px-4 py-2 text-xs font-semibold text-muted uppercase tracking-wide text-right">{data.climate_year}</th>
              <th className="px-8 py-2 text-xs font-semibold text-muted uppercase tracking-wide text-right">Δ</th>
            </tr>
          </thead>
          <tbody>
            {data.climate_diff.map((row, i) => (
              <tr key={row.label} className={i % 2 === 0 ? 'bg-white' : 'bg-rose-mist/10'}>
                <td className="px-8 py-2 text-slate font-medium">{row.label}</td>
                <td className="px-4 py-2 text-slate text-right tabular-nums">{fmt(row.base)}</td>
                <td className="px-4 py-2 text-slate text-right tabular-nums">{fmt(row.counterfactual)}</td>
                <td className={`px-8 py-2 text-right tabular-nums font-semibold ${deltaClass(row.delta)}`}>
                  {row.delta > 0 ? '+' : ''}{fmt(row.delta)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* analysis */}
      <div className="px-8 py-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted mb-3">Analysis</p>
        <p className="text-slate text-sm leading-relaxed">{data.analysis}</p>
      </div>
    </div>
  )
}

function PredCol({
  label, brix, tons, brixDelta, tonsDelta, muted,
}: {
  label: string
  brix: number
  tons: number
  brixDelta?: number
  tonsDelta?: number
  muted?: boolean
}) {
  return (
    <div className="px-6 py-5 space-y-4">
      <p className="text-xs font-semibold uppercase tracking-widest text-muted">{label}</p>
      <div>
        <p className={`text-2xl font-bold ${muted ? 'text-muted' : 'text-slate'}`}>
          {brix.toFixed(1)}<span className="text-sm font-normal text-muted ml-1">°Bx</span>
        </p>
        {brixDelta !== undefined && (
          <p className={`text-xs mt-0.5 font-semibold ${deltaClass(brixDelta)}`}>
            {brixDelta > 0 ? '+' : ''}{brixDelta.toFixed(1)} vs base
          </p>
        )}
      </div>
      <div>
        <p className={`text-2xl font-bold ${muted ? 'text-muted' : 'text-slate'}`}>
          {tons >= 1000 ? `${(tons / 1000).toFixed(1)}k` : tons.toFixed(0)}
          <span className="text-sm font-normal text-muted ml-1">tons</span>
        </p>
        {tonsDelta !== undefined && (
          <p className={`text-xs mt-0.5 font-semibold ${deltaClass(tonsDelta)}`}>
            {tonsDelta > 0 ? '+' : ''}{Math.abs(tonsDelta).toLocaleString()} tons vs base
          </p>
        )}
      </div>
    </div>
  )
}

function deltaClass(delta: number): string {
  if (delta > 0) return 'text-amber-600'
  if (delta < 0) return 'text-sky-600'
  return 'text-muted'
}

function fmt(n: number): string {
  if (Math.abs(n) >= 100) return Math.round(n).toLocaleString()
  if (Math.abs(n) >= 10) return n.toFixed(1)
  return n.toFixed(2)
}

function round1(n: number): number {
  return Math.round(n * 10) / 10
}

function SwapIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      className="w-5 h-5 text-wine" aria-hidden="true">
      <path d="M7 16V4m0 0L3 8m4-4 4 4" />
      <path d="M17 8v12m0 0 4-4m-4 4-4-4" />
    </svg>
  )
}
