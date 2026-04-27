import { useState } from 'react'
import Header from './components/Header'
import AboutView from './components/AboutView'
import AdvisoryForm, { type FormValues } from './components/AdvisoryForm'
import AdvisoryCard, { type AdvisoryResponse } from './components/AdvisoryCard'
import ChatView from './components/ChatView'

type Tab = 'about' | 'advisory' | 'chat'
type ApiError = { detail: string }

export default function App() {
  const [tab, setTab] = useState<Tab>('about')

  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AdvisoryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleAdvisorySubmit = async (values: FormValues) => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch('/api/advisory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
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
    <div className="min-h-screen bg-cream flex flex-col">
      <Header activeTab={tab} onTabChange={setTab} />

      {tab === 'about' && <AboutView onNavigate={setTab} />}

      {tab === 'advisory' && (
        <main className="flex-1 w-full max-w-3xl mx-auto px-4 py-10 space-y-6">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-slate tracking-tight">
              Climate-Informed Decisions
            </h1>
            <p className="mt-2 text-muted text-sm max-w-md mx-auto">
              Harvest forecasts for Napa Valley small vintners, powered by 34
              years of climate and crush data.
            </p>
          </div>

          <AdvisoryForm onSubmit={handleAdvisorySubmit} loading={loading} />

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
              {error}
            </div>
          )}

          {result && <AdvisoryCard data={result} />}
        </main>
      )}

      {tab === 'chat' && <ChatView />}
    </div>
  )
}
