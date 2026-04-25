# In dev (Docker): VITE_API_BASE is not set → falls back to '' → /api/v1 → proxied by Vite to backend
# In prod (Vercel): VITE_API_BASE=https://playto-backend.onrender.com → full URL to Render
const BASE = `${import.meta.env.VITE_API_BASE ?? ''}/api/v1`

export async function getMerchants() {
  const r = await fetch(`${BASE}/merchants/`)
  if (!r.ok) throw new Error('Failed to fetch merchants')
  return r.json()
}

export async function getMerchant(id) {
  const r = await fetch(`${BASE}/merchants/${id}/`)
  if (!r.ok) throw new Error('Failed to fetch merchant')
  return r.json()
}

export async function getPayouts(merchantId) {
  const r = await fetch(`${BASE}/payouts/list/?merchant_id=${merchantId}`)
  if (!r.ok) throw new Error('Failed to fetch payouts')
  return r.json()
}

export async function createPayout({ merchantId, amountPaise, bankAccountId, idempotencyKey }) {
  const r = await fetch(`${BASE}/payouts/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify({
      merchant_id: merchantId,
      amount_paise: amountPaise,
      bank_account_id: bankAccountId,
    }),
  })
  const data = await r.json()
  if (!r.ok) throw new Error(data.error || 'Payout failed')
  return data
}
