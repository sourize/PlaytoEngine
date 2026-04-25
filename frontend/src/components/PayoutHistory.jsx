const STATUS_STYLES = {
  pending:    'bg-slate-100 text-slate-600',
  processing: 'bg-amber-100 text-amber-700',
  completed:  'bg-emerald-100 text-emerald-700',
  failed:     'bg-red-100 text-red-600',
}

function formatPaise(paise) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', minimumFractionDigits: 2,
  }).format(paise / 100)
}

export default function PayoutHistory({ payouts }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
      <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
        <h2 className="font-medium text-slate-800">Payout History</h2>
        <span className="text-xs text-slate-400">Auto-refreshes every 5s</span>
      </div>

      {payouts.length === 0 ? (
        <p className="text-center py-8 text-slate-400 text-sm">No payouts yet</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left">
                <th className="px-5 py-3 text-xs font-medium text-slate-500">ID</th>
                <th className="px-5 py-3 text-xs font-medium text-slate-500">Amount</th>
                <th className="px-5 py-3 text-xs font-medium text-slate-500">Bank</th>
                <th className="px-5 py-3 text-xs font-medium text-slate-500">Status</th>
                <th className="px-5 py-3 text-xs font-medium text-slate-500">Attempts</th>
                <th className="px-5 py-3 text-xs font-medium text-slate-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {payouts.map(p => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="px-5 py-3 font-mono text-xs text-slate-500">
                    {String(p.id).slice(0, 8)}…
                  </td>
                  <td className="px-5 py-3 font-medium text-slate-800">
                    {formatPaise(p.amount_paise)}
                  </td>
                  <td className="px-5 py-3 text-slate-600">{p.bank_account_id}</td>
                  <td className="px-5 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[p.status]}`}>
                      {p.status}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-500">{p.attempt_count}</td>
                  <td className="px-5 py-3 text-slate-500 text-xs">
                    {new Date(p.created_at).toLocaleString('en-IN')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
