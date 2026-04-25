import { useState, useEffect, useCallback } from 'react'
import { getMerchant, getPayouts } from '../api'
import PayoutForm from './PayoutForm'
import PayoutHistory from './PayoutHistory'

function formatPaise(paise) {
  const rupees = paise / 100
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
  }).format(rupees)
}

function BalanceCard({ label, amount, color }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <p className="text-sm text-slate-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{formatPaise(amount)}</p>
      <p className="text-xs text-slate-400 mt-1">{amount.toLocaleString()} paise</p>
    </div>
  )
}

export default function Dashboard({ merchant }) {
  const [data, setData] = useState(null)
  const [payouts, setPayouts] = useState([])

  const refresh = useCallback(() => {
    getMerchant(merchant.id).then(setData)
    getPayouts(merchant.id).then(setPayouts)
  }, [merchant.id])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 5000) // Poll every 5s
    return () => clearInterval(interval)
  }, [refresh])

  if (!data) return <div className="text-center py-10 text-slate-400">Loading...</div>

  return (
    <div className="space-y-6">
      {/* Balance Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <BalanceCard
          label="Available Balance"
          amount={data.available_balance}
          color="text-emerald-600"
        />
        <BalanceCard
          label="Held Balance"
          amount={data.held_balance}
          color="text-amber-500"
        />
        <BalanceCard
          label="Total Balance"
          amount={data.available_balance + data.held_balance}
          color="text-slate-700"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Payout Form */}
        <div className="lg:col-span-1">
          <PayoutForm merchant={data} onSuccess={refresh} />
        </div>

        {/* Ledger */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="font-medium text-slate-800">Recent Ledger Entries</h2>
            </div>
            <div className="divide-y divide-slate-50">
              {data.recent_entries.length === 0 && (
                <p className="text-center py-6 text-slate-400 text-sm">No entries yet</p>
              )}
              {data.recent_entries.map(entry => (
                <div key={entry.id} className="px-5 py-3 flex items-center justify-between">
                  <div>
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                      entry.entry_type === 'credit'
                        ? 'bg-emerald-50 text-emerald-700'
                        : entry.entry_type === 'debit_hold'
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-blue-50 text-blue-700'
                    }`}>
                      {entry.entry_type.replace('_', ' ')}
                    </span>
                    <span className="ml-2 text-sm text-slate-600">{entry.description}</span>
                  </div>
                  <span className={`text-sm font-semibold ${entry.amount_paise > 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                    {entry.amount_paise > 0 ? '+' : ''}{formatPaise(entry.amount_paise)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Payout History */}
      <PayoutHistory payouts={payouts} />
    </div>
  )
}
