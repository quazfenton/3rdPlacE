export default function AnalogFooter() {
  return (
    <footer style={{
      borderTop:'2px solid var(--border-dim)',
      background:'linear-gradient(180deg, #0D0A06 0%, #090806 100%)',
      padding:'24px 20px 20px',
    }}>
      <div style={{
        display:'flex', flexWrap:'wrap', justifyContent:'space-between',
        alignItems:'flex-end', gap:20, maxWidth:800, margin:'0 auto',
      }}>
        {/* Knob */}
        <div style={{ display:'flex', flexDirection:'column', alignItems:'center', gap:4 }}>
          <div style={{
            width:32, height:32, borderRadius:'50%',
            border:'3px solid var(--border-dim)',
            background:'radial-gradient(circle at 35% 35%, #2A1C00, #120F0A)',
            position:'relative',
          }}>
            <div style={{
              position:'absolute', top:2, left:'50%', width:3, height:12,
              background:'var(--amber)', transform:'translateX(-50%)',
              borderRadius:2,
            }} />
          </div>
          <span style={{ fontSize:8, letterSpacing:2, color:'var(--text-dim)' }}>VOL</span>
        </div>

        {/* Center text */}
        <div style={{ textAlign:'center' }}>
          <p style={{
            fontFamily:'VT323', fontSize:16, color:'var(--text-dim)',
            letterSpacing:3,
          }}>
            ═══ 3RDPLACE PROTOCOL ═══
          </p>
          <p style={{
            fontFamily:'IBM Plex Mono', fontSize:9, color:'var(--text-dim)',
            marginTop:6, letterSpacing:1, opacity:0.6,
          }}>
            COMMUNITY INSURANCE & ACCESS LAYER v0.1
          </p>
        </div>

        {/* Knob */}
        <div style={{ display:'flex', flexDirection:'column', alignItems:'center', gap:4 }}>
          <div style={{
            width:32, height:32, borderRadius:'50%',
            border:'3px solid var(--border-dim)',
            background:'radial-gradient(circle at 35% 35%, #2A1C00, #120F0A)',
            position:'relative',
          }}>
            <div style={{
              position:'absolute', top:2, left:'50%', width:3, height:12,
              background:'var(--cyan)', transform:'translateX(-50%) rotate(45deg)',
              borderRadius:2,
            }} />
          </div>
          <span style={{ fontSize:8, letterSpacing:2, color:'var(--text-dim)' }}>MHz</span>
        </div>
      </div>
    </footer>
  )
}
