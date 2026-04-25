import { useState, useEffect } from 'react'
import { getMerchants } from './api'
import Dashboard from './components/Dashboard'

export default function App() {
  const [merchants, setMerchants] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)

  const [error, setError] = useState(null)

  useEffect(() => {
    getMerchants().then(data => {
      setMerchants(data)
      if (data.length > 0) setSelected(data[0])
      setLoading(false)
    }).catch(err => {
      console.error(err)
      setError(err.message || 'Failed to connect to backend')
      setLoading(false)
    })
  }, [])

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
            <span className="text-white text-sm font-bold">P</span>
          </div>
          <h1 className="text-lg font-semibold text-slate-900">Playto Pay</h1>
          <span className="text-slate-400 text-sm">· Merchant Dashboard</span>
        </div>
        {merchants.length > 0 && (
          <select
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm text-slate-700 bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            onChange={e => setSelected(merchants.find(m => m.id == e.target.value))}
            value={selected?.id || ''}
          >
            {merchants.map(m => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        )}
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {error ? (
          <div className="text-center py-20 text-red-500">
            <p className="font-semibold text-lg">Connection Error</p>
            <p className="text-sm mt-2">{error}</p>
            <p className="text-sm mt-4 text-slate-500">Did you set VITE_API_BASE in Vercel before deploying?</p>
          </div>
        ) : loading ? (
          <div className="text-center py-20 text-slate-500">Loading...</div>
        ) : selected ? (
          <Dashboard merchant={selected} />
        ) : (
          <div className="text-center py-20 text-slate-500">No merchants found. Run the seed command.</div>
        )}
      </main>
    </div>
  )
}
