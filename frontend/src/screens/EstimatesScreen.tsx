import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { EstimateHero } from '../components/EstimateHero'
import { VerificationLogPanel } from '../components/VerificationLog'
import { useSession } from '../context/SessionContext'

export function EstimatesScreen() {
  const { address, analysis, setAnalysis } = useSession()
  const [loading, setLoading] = useState(!analysis)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (analysis) return
    const lmk = address?.lmk_key ?? 'sam-demo-1'
    let cancelled = false
    void api
      .fetchAnalysis(lmk)
      .then((a) => {
        if (!cancelled) setAnalysis(a)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetch once per address; analysis update must not cancel in-flight request
  }, [address?.lmk_key, setAnalysis])

  if (loading) return <p className="loading">Computing fabric vs measured…</p>
  if (error) return <p className="error">{error}</p>
  if (!analysis) return null

  return (
    <section className="screen estimates-screen">
      <h1>Two estimates</h1>
      <EstimateHero analysis={analysis} />
      <VerificationLogPanel visible={true} />
      <p className="cta-row">
        <Link className="btn primary" to="/cost">Running costs</Link>
      </p>
    </section>
  )
}
