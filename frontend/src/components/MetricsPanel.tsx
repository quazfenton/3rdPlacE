import { useState, useEffect } from 'react'

const metrics = [
  { label:'PARTICIPANTS', value:1283, suffix:'', color:'var(--amber)' },
  { label:'ACTIVE SPACES', value:47, suffix:'', color:'var(--cyan)' },
  { label:'COVERAGE', value:99.7, suffix:'%', color:'var(--green-term)' },
  { label:'UPTIME', value:100, suffix:'%', color:'var(--green-term)' },
]

function AnimatedNumber({ target, suffix, color }: { target: number; suffix: string; color: string }) {
  const [val, setVal] = useState(0)

  useEffect(() => {
    const dur = 2000
    const start = performance.now()
    let raf: number
    function tick(now: number) {
      const t = Math.min((now - start) / dur, 1)
      setVal(t * target)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target])

  return (
    <span style={{ color }}>
      {target < 100 ? val.toFixed(1) : Math.round(val).toLocaleString()}{suffix}
    </span>
  )
}

export default function MetricsPanel() {
  const [ready, setReady] = useState(false)
  useEffect(() => { setReady(true) }, [])

  return (
    <div style={{
      display:'grid', gridTemplateColumns:'1fr 1fr', gap:1,
      border:'2px solid var(--border-dim)',
      background:'var(--border-dim)',
      fontFamily:'IBM Plex Mono',
    }}>
      {metrics.map((m, i) => (
        <div key={i} style={{
          background:'#0A0805',
          padding:'14px 12px',
          display:'flex', flexDirection:'column', alignItems:'center', gap:2,
        }}>
          <span style={{ fontSize:9, letterSpacing:2, color:'var(--text-dim)' }}>
            {m.label}
          </span>
          <span style={{
            fontSize:22, fontWeight:700, fontFamily:'VT323',
            letterSpacing:1,
            color: m.color,
          }}>
            {ready ? <AnimatedNumber target={m.value} suffix={m.suffix} color={m.color} /> : '0'}
          </span>
        </div>
      ))}
    </div>
  )
}
