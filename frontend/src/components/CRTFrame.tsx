import type { ReactNode } from 'react'

export default function CRTFrame({ children }: { children: ReactNode }) {
  return (
    <div style={{
      position:'relative',
      border:'4px solid var(--border-dim)',
      borderRadius:'28px 28px 20px 20px',
      padding:'12px',
      background:'linear-gradient(135deg, #1A140C 0%, #120F0A 50%, #1A140C 100%)',
      boxShadow:
        'inset 0 0 30px rgba(0,0,0,0.8), 0 0 40px var(--shadow-glow), 0 0 80px var(--shadow-glow)',
    }}>
      <div style={{
        position:'relative',
        borderRadius:'18px 18px 12px 12px',
        overflow:'hidden',
        background:'var(--bg-screen)',
        border:'2px solid #2A1C00',
        boxShadow:'inset 0 0 60px rgba(0,0,0,0.9)',
        aspectRatio:'4/3',
        maxHeight:'70vh',
      }}>
        {children}
      </div>
      <div style={{
        display:'flex', justifyContent:'center', gap:16, marginTop:10, alignItems:'center',
      }}>
        <div style={{
          width:8, height:8, borderRadius:'50%',
          background:'var(--green-term)',
          boxShadow:'0 0 8px var(--green-term), 0 0 16px rgba(51,255,51,0.3)',
        }} />
        <span style={{
          fontFamily:'VT323', fontSize:14, color:'var(--text-dim)',
          letterSpacing:4, textTransform:'uppercase',
        }}>
          system online
        </span>
      </div>
    </div>
  )
}
