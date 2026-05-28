import { useState } from 'react'

const controls = [
  { id:'about', label:'ABOUT', defaultOn:true },
  { id:'features', label:'FEATURES', defaultOn:false },
  { id:'metrics', label:'METRICS', defaultOn:false },
  { id:'protocol', label:'PROTOCOL', defaultOn:false },
]

export default function ControlPanel({ onNavigate }: { onNavigate: (id: string) => void }) {
  const [active, setActive] = useState('about')

  const handleToggle = (id: string) => {
    setActive(id)
    onNavigate(id)
  }

  return (
    <div style={{
      display:'flex', flexWrap:'wrap', justifyContent:'center', gap:6,
      padding:'16px 12px',
      background:'linear-gradient(180deg, #120F0A 0%, #0D0A06 100%)',
      border:'2px solid var(--border-dim)',
    }}>
      {controls.map(c => {
        const isOn = active === c.id
        return (
          <button
            key={c.id}
            onClick={() => handleToggle(c.id)}
            style={{
              all:'unset', cursor:'pointer',
              display:'flex', flexDirection:'column', alignItems:'center', gap:6,
              padding:'8px 14px',
              minWidth:90,
            }}
          >
            {/* Toggle switch visual */}
            <div style={{
              width:20, height:32,
              border:'2px solid var(--border-dim)',
              borderRadius:4,
              background:'#1A140C',
              position:'relative',
              cursor:'pointer',
              transition:'border-color 0.2s',
              borderColor: isOn ? 'var(--amber)' : 'var(--border-dim)',
            }}>
              <div style={{
                position:'absolute',
                left:2, right:2,
                height:12,
                borderRadius:2,
                background: isOn ? 'var(--amber)' : '#3A2800',
                top: isOn ? 14 : 4,
                transition:'top 0.15s, background 0.15s',
                boxShadow: isOn ? '0 0 8px var(--amber)' : 'none',
              }} />
            </div>
            {/* Label */}
            <span style={{
              fontFamily:'IBM Plex Mono', fontSize:10,
              letterSpacing:2, fontWeight:600,
              color: isOn ? 'var(--amber)' : 'var(--text-dim)',
              transition:'color 0.2s',
            }}>
              {c.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
