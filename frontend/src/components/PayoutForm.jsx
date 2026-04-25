import { useState } from 'react'
import { createPayout } from '../api'

function generateKey() {
  return crypto.randomUUID()
}

export default function PayoutForm({ merchant, onSuccess }) {
  const [amountRupees, setAmountRupees] = useState('')
  const [bankAccount, setBankAccount] = useState('HDFC0001234')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function handleSubmit() {
    setLoading(true)
    setResult(null)
    setError(null)

    const amountPaise = Math.round(parseFloat(amountRupees) * 100)
    if (!amountPaise || amountPaise <= 0) {
      setError('Enter a valid amount')
      setLoading(false)
      return
    }

    try {
      const payout = await createPayout({
        merchantId: merchant.id,
        amountPaise,
        bankAccountId: bankAccount,
        idempotencyKey: generateKey(),
      })
      setResult(payout)
      setAmountRupees('')
      onSuccess()
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <h2 className="font-medium text-slate-800 mb-4">Request Payout</h2>

      <div className="space-y-3">
        <div>
          <label className="block text-xs text-slate-500 mb-1">Amount (₹)</label>
          <input
            type="number"
            min="1"
            step="0.01"
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            placeholder="e.g. 500"
            value={amountRupees}
            onChange={e => setAmountRupees(e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs text-slate-500 mb-1">Bank Account ID</label>
          <input
            type="text"
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            value={bankAccount}
            onChange={e => setBankAccount(e.target.value)}
          />
        </div>

        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full bg-indigo-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? 'Submitting...' : 'Request Payout'}
        </button>
      </div>

      {result && (
        <div className="mt-3 p-3 bg-emerald-50 border border-emerald-200 rounded-lg">
          <p className="text-xs font-medium text-emerald-700">Payout created!</p>
          <p className="text-xs text-emerald-600 mt-1 font-mono break-all">{result.id}</p>
          <p className="text-xs text-emerald-600">Status: {result.status}</p>
        </div>
      )}

      {error && (
        <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-xs font-medium text-red-700">{error}</p>
        </div>
      )}
    </div>
  )
}
