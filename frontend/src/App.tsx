import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import CRTFrame from './components/CRTFrame'
import Hero3D from './components/Hero3D'
import ControlPanel from './components/ControlPanel'
import TerminalFeed from './components/TerminalFeed'
import MetricsPanel from './components/MetricsPanel'
import AnalogFooter from './components/AnalogFooter'
import NoiseOverlay from './components/NoiseOverlay'

function GlitchText({ children, style }: { children: string; style?: React.CSSProperties }) {
  const [glitching, setGlitching] = useState(false)

  useEffect(() => {
    const iv = setInterval(() => {
      setGlitching(Math.random() < 0.15)
      setTimeout(() => setGlitching(false), 150)
    }, 3000)
    return () => clearInterval(iv)
  }, [])

  return (
    <span
      className={glitching ? 'glitch' : ''}
      style={{
        fontFamily:'VT323',
        fontSize:32,
        letterSpacing:4,
        color:'var(--amber)',
        textShadow:'0 0 20px rgba(255,176,0,0.3)',
        ...style,
      }}
    >
      {children}
      <style>{`
        .glitch {
          animation: glitch 0.15s ease-in-out 2;
        }
      `}</style>
    </span>
  )
}

const sections: Record<string, { title: string; content: string }> = {
  about: {
    title: 'THE THIRD PLACE',
    content: 'A protocol for community gatherings. Insurance, access, and coordination — automated. Third spaces are where community happens. We make them sustainable.',
  },
  features: {
    title: 'CORE SYSTEMS',
    content: 'Pay-per-event insurance classification. Dynamic pricing by risk profile. Access control integration. Real-time verification. Claims management. All wrapped in a unified API.',
  },
  metrics: {
    title: 'NETWORK STATUS',
    content: 'Live metrics from the protocol layer. Coverage zones, active envelopes, participant counts, and system health monitoring across all connected spaces.',
  },
  protocol: {
    title: 'OPEN PROTOCOL',
    content: 'Built on open standards. RESTful API with role-based access. Extensible lock integration. Transparent pricing engine. Self-sovereign participant identities.',
  },
}

export default function App() {
  const [activeSection, setActiveSection] = useState('about')
  const [powerOn, setPowerOn] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setPowerOn(true), 100)
    return () => clearTimeout(t)
  }, [])

  return (
    <div className={`app-container crt-flicker ${powerOn ? 'power-on' : ''}`}>
      <NoiseOverlay />
      <div className="crt-overlay" />

      <main style={{
        maxWidth: 900, margin: '0 auto',
        padding: '16px 12px 0',
        display: 'flex', flexDirection: 'column', gap: 10,
        minHeight: '100vh',
      }}>
        {/* SECTION 1: CRT MONITOR with 3D scene */}
        <section style={{
          animation: powerOn ? 'powerOn 1.2s ease-out' : 'none',
        }}>
          <CRTFrame>
            <Hero3D />
          </CRTFrame>
        </section>

        {/* SECTION 2: Title + Tagline */}
        <section style={{
          textAlign: 'center',
          padding: '8px 12px',
          border: '2px solid var(--border-dim)',
          background: 'linear-gradient(90deg, transparent, rgba(255,176,0,0.03), transparent)',
        }}>
          <GlitchText>3RDPLACE</GlitchText>
          <p style={{
            fontFamily:'IBM Plex Mono', fontSize:11, letterSpacing:3,
            color:'var(--text-dim)', marginTop:2, textTransform:'uppercase',
          }}>
            Community Insurance &amp; Access Protocol
          </p>
        </section>

        {/* SECTION 3: Control Panel */}
        <ControlPanel onNavigate={setActiveSection} />

        {/* SECTION 4: Content panels — asymmetrical layout */}
        <div style={{
          display:'grid',
          gridTemplateColumns: '1fr',
          gap: 1,
          background: 'var(--border-dim)',
          border: '2px solid var(--border-dim)',
        }}>
          {/* Top row: Terminal + Metrics side by side */}
          <div style={{
            display:'grid',
            gridTemplateColumns: '1.6fr 1fr',
            gap: 1,
            background: 'var(--border-dim)',
          }}>
            <div style={{ background:'var(--bg)' }}>
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeSection}
                  initial={{ opacity:0, y:8 }}
                  animate={{ opacity:1, y:0 }}
                  exit={{ opacity:0, y:-8 }}
                  transition={{ duration:0.25 }}
                  style={{ padding:'16px' }}
                >
                  <h2 style={{
                    fontFamily:'VT323', fontSize:20,
                    color:'var(--amber)',
                    letterSpacing:3, marginBottom:8,
                    textShadow:'0 0 10px rgba(255,176,0,0.2)',
                  }}>
                    {'>'} {sections[activeSection].title}
                  </h2>
                  <p style={{
                    fontFamily:'IBM Plex Mono', fontSize:11,
                    lineHeight:1.8, color:'var(--text)',
                    letterSpacing:0.5,
                  }}>
                    {sections[activeSection].content}
                  </p>
                </motion.div>
              </AnimatePresence>
            </div>
            <MetricsPanel />
          </div>

          {/* Bottom row: Terminal feed spans full width */}
          <div style={{ background:'var(--bg)' }}>
            <TerminalFeed />
          </div>
        </div>

        {/* Spacer */}
        <div style={{ flex:1 }} />

        {/* SECTION 6: Footer with analog controls */}
        <AnalogFooter />
      </main>
    </div>
  )
}
