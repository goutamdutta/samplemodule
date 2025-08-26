import { useEffect, useRef, useState } from 'react'
import './App.css'

function App() {
  const [messages, setMessages] = useState([{ role: 'system', content: 'You are a helpful assistant.' }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const listRef = useRef(null)

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages])

  async function sendMessage(e) {
    e.preventDefault()
    const trimmed = input.trim()
    if (!trimmed || loading) return
    const next = [...messages, { role: 'user', content: trimmed }]
    setMessages(next)
    setInput('')
    setLoading(true)
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: next.filter(m => m.role !== 'system') }),
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      const content = data.content || data.raw?.choices?.[0]?.message?.content || ''
      setMessages(prev => [...prev, { role: 'assistant', content }])
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${String(err)}` }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 16 }}>
      <h1>Groq Chatbot</h1>
      <div ref={listRef} style={{ height: 400, overflowY: 'auto', border: '1px solid #eee', borderRadius: 8, padding: 12, background: '#fafafa' }}>
        {messages.filter(m => m.role !== 'system').map((m, i) => (
          <div key={i} style={{ marginBottom: 12, display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{ maxWidth: '80%', padding: '8px 12px', borderRadius: 12, background: m.role === 'user' ? '#4f46e5' : 'white', color: m.role === 'user' ? 'white' : '#111', border: '1px solid #e5e7eb' }}>
              <strong style={{ display: 'block', marginBottom: 4 }}>{m.role === 'user' ? 'You' : 'Assistant'}</strong>
              <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
            </div>
          </div>
        ))}
        {loading && <div>Thinking…</div>}
      </div>
      <form onSubmit={sendMessage} style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Type a message" style={{ flex: 1, padding: 10, borderRadius: 8, border: '1px solid #e5e7eb' }} />
        <button type="submit" disabled={loading} style={{ padding: '10px 16px', borderRadius: 8 }}>
          Send
        </button>
      </form>
    </div>
  )
}

export default App
