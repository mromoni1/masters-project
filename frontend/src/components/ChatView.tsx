import { useEffect, useRef, useState } from 'react'

type Role = 'user' | 'assistant'

type Message = {
  role: Role
  content: string
}

type ApiError = { detail: string }

const SUGGESTIONS = [
  'What year had the highest Brix for Cabernet Sauvignon?',
  'How has heat stress changed over the past decade?',
  'Which variety is most sensitive to drought years?',
  'Compare 2021 and 2022 growing seasons.',
]

export default function ChatView() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || loading) return

    const next: Message[] = [...messages, { role: 'user', content: trimmed }]
    setMessages(next)
    setInput('')
    setLoading(true)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: next }),
      })
      if (!res.ok) {
        const err: ApiError = await res.json()
        throw new Error(err.detail ?? `Server error ${res.status}`)
      }
      const { reply } = await res.json()
      setMessages([...next, { role: 'assistant', content: reply }])
    } catch (e) {
      setMessages([
        ...next,
        {
          role: 'assistant',
          content: `Sorry, something went wrong: ${e instanceof Error ? e.message : 'unknown error'}`,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    send(input)
  }

  return (
    <div className="flex-1 flex flex-col w-full max-w-3xl mx-auto px-4 py-6 min-h-0">
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-slate tracking-tight">Ask the Data</h1>
        <p className="text-sm text-muted mt-1">
          Ask anything about 35 years of Napa Valley climate and harvest data.
        </p>
      </div>

      {/* message thread */}
      <div className="flex-1 overflow-y-auto space-y-4 pb-4">
        {messages.length === 0 && (
          <div className="space-y-3 pt-2">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted">Try asking</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="text-left px-4 py-3 rounded-xl border border-rose-mist bg-white text-sm text-slate hover:border-wine/40 hover:bg-rose-mist/30 transition"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <Bubble key={i} message={m} />
        ))}

        {loading && (
          <div className="flex gap-3 items-start">
            <div className="flex items-center justify-center w-8 h-8 rounded-full bg-wine shrink-0 mt-0.5">
              <GrapeIcon />
            </div>
            <div className="bg-white border border-rose-mist/60 rounded-2xl rounded-tl-sm px-4 py-3">
              <TypingDots />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* input bar */}
      <form
        onSubmit={handleSubmit}
        className="flex gap-2 mt-2 bg-white border border-rose-mist/60 rounded-xl p-2 shadow-sm"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about the data…"
          className="flex-1 px-3 py-2 text-sm text-slate bg-transparent focus:outline-none placeholder:text-muted/60"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="px-4 py-2 rounded-lg bg-wine text-cream text-sm font-semibold hover:bg-wine-dark transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Send
        </button>
      </form>
    </div>
  )
}

function Bubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] bg-wine text-cream rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-3 items-start">
      <div className="flex items-center justify-center w-8 h-8 rounded-full bg-wine shrink-0 mt-0.5">
        <GrapeIcon />
      </div>
      <div className="max-w-[80%] bg-white border border-rose-mist/60 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-slate leading-relaxed whitespace-pre-wrap">
        {message.content}
      </div>
    </div>
  )
}

function TypingDots() {
  return (
    <div className="flex gap-1 items-center h-5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-muted animate-bounce"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </div>
  )
}

function GrapeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-cream" aria-hidden="true">
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
