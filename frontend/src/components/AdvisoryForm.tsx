export type FormValues = {
  variety: string
  year: number
}

type Props = {
  onSubmit: (values: FormValues) => void
  loading: boolean
}

const VARIETIES = ['Cabernet Sauvignon', 'Pinot Noir', 'Chardonnay']

const MAX_YEAR = 2024
const YEARS = Array.from({ length: MAX_YEAR - 1991 }, (_, i) => MAX_YEAR - i)

export default function AdvisoryForm({ onSubmit, loading }: Props) {
  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const data = new FormData(e.currentTarget)
    onSubmit({
      variety: data.get('variety') as string,
      year: Number(data.get('year')),
    })
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-rose-mist/60 p-8">
      <div className="flex items-center gap-3 mb-2">
        <div className="flex items-center justify-center w-10 h-10 rounded-full bg-rose-mist shrink-0">
          <VineyardIcon />
        </div>
        <div>
          <h2 className="text-xl font-bold text-slate leading-tight">Get a Harvest Advisory</h2>
          <p className="text-sm text-muted">
            Select your variety and season year to generate a climate-informed forecast.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="mt-6 space-y-5">
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <label className="block">
            <span className="text-sm font-semibold text-slate mb-1.5 block">Grape Variety</span>
            <select
              name="variety"
              defaultValue="Cabernet Sauvignon"
              className="w-full rounded-lg border border-rose-mist bg-cream px-4 py-2.5 text-slate text-sm focus:outline-none focus:ring-2 focus:ring-wine/40 focus:border-wine transition"
            >
              {VARIETIES.map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="text-sm font-semibold text-slate mb-1.5 block">Season Year</span>
            <select
              name="year"
              defaultValue={MAX_YEAR}
              className="w-full rounded-lg border border-rose-mist bg-cream px-4 py-2.5 text-slate text-sm focus:outline-none focus:ring-2 focus:ring-wine/40 focus:border-wine transition"
            >
              {YEARS.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </label>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-wine text-cream font-semibold py-3 text-sm tracking-wide hover:bg-wine-dark active:scale-[0.99] transition disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {loading ? 'Generating Advisory…' : 'Generate Advisory'}
        </button>
      </form>
    </div>
  )
}

function VineyardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      className="w-5 h-5 text-wine" aria-hidden="true">
      <path d="M12 2a7 7 0 0 1 7 7c0 5-7 13-7 13S5 14 5 9a7 7 0 0 1 7-7z" />
      <circle cx="12" cy="9" r="2.5" />
    </svg>
  )
}
