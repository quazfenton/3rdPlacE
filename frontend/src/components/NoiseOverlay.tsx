import { useEffect, useRef } from 'react'

export default function NoiseOverlay() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = window.innerWidth
    canvas.height = window.innerHeight

    let frame = 0
    let running = true

    function draw() {
      if (!running) return
      frame++
      if (frame % 3 !== 0) { requestAnimationFrame(draw); return }
      const w = canvas!.width
      const h = canvas!.height
      const imageData = ctx!.createImageData(w, h)
      const data = imageData.data
      for (let i = 0; i < data.length; i += 4) {
        const v = Math.random() * 255
        data[i] = v
        data[i+1] = v
        data[i+2] = v
        data[i+3] = 18
      }
      ctx!.putImageData(imageData, 0, 0)
      requestAnimationFrame(draw)
    }
    draw()

    const resize = () => {
      canvas!.width = window.innerWidth
      canvas!.height = window.innerHeight
    }
    window.addEventListener('resize', resize)
    return () => { running = false; window.removeEventListener('resize', resize) }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position:'fixed', inset:0, width:'100vw', height:'100vh',
        pointerEvents:'none', zIndex:9997, opacity:0.5, mixBlendMode:'screen'
      }}
    />
  )
}
