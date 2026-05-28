import { useState, useEffect } from 'react'

const lines = [
  { text: '> 3rdPlacE protocol v0.1.0', delay: 0 },
  { text: '> initializing community insurance layer...', delay: 600 },
  { text: '> scanning for active spaces...', delay: 1200 },
  { text: '> 12 community hubs detected', delay: 1800 },
  { text: '> access control nodes: ONLINE', delay: 2200 },
  { text: '> insurance envelopes: 47 active', delay: 2700 },
  { text: '> system ready. awaiting participants.', delay: 3300 },
]

export default function TerminalFeed() {
  const [visible, setVisible] = useState(0)
  const [showCursor, setShowCursor] = useState(true)

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = []
    lines.forEach((l, i) => {
      const t = setTimeout(() => setVisible(i + 1), l.delay)
      timers.push(t)
    })
    return () => timers.forEach(clearTimeout)
  }, [])

  useEffect(() => {
    const iv = setInterval(() => setShowCursor(c => !c), 530)
    return () => clearInterval(iv)
  }, [])

  return (
    <div style={{
      background:'#0A0805',
      border:'2px solid var(--border-dim)',
      padding:'16px 20px',
      minHeight:220,
      fontFamily:'VT323',
      fontSize:18,
      lineHeight:1.5,
      color:'var(--green-term)',
      position:'relative',
      boxShadow:'inset 0 0 20px rgba(0,0,0,0.5)',
    }}>
      <div style={{
        display:'flex', gap:8, marginBottom:12,
        borderBottom:'1px solid var(--border-dim)',
        paddingBottom:8,
      }}>
        <div style={{width:8,height:8,borderRadius:'50%',background:'var(--red-alert)'}} />
        <div style={{width:8,height:8,borderRadius:'50%',background:'var(--amber)'}} />
        <div style={{width:8,height:8,borderRadius:'50%',background:'var(--green-term)'}} />
      </div>
      {lines.slice(0, visible).map((l, i) => (
        <div key={i} style={{
          opacity:0, animation:'fadeIn 0.05s forwards',
        }}>
          {l.text}
        </div>
      ))}
      {visible <= lines.length && (
        <span style={{
          opacity: showCursor ? 1 : 0,
          transition:'opacity 0.1s',
        }}>█</span>
      )}
      <style>{`
        @keyframes fadeIn { to { opacity: 1; } }
      `}</style>
    </div>
  )
}
