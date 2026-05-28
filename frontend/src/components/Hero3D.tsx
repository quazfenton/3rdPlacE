import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'

function TorusKnot() {
  const meshRef = useRef<THREE.Mesh>(null)
  const wireRef = useRef<THREE.Mesh>(null)

  useFrame((_, delta) => {
    if (meshRef.current) {
      meshRef.current.rotation.x += delta * 0.15
      meshRef.current.rotation.y += delta * 0.12
    }
    if (wireRef.current) {
      wireRef.current.rotation.x += delta * 0.15
      wireRef.current.rotation.y += delta * 0.12
    }
  })

  return (
    <group>
      <mesh ref={meshRef}>
        <torusKnotGeometry args={[1.4, 0.45, 180, 24]} />
        <meshStandardMaterial
          color="#FFB000"
          emissive="#E07000"
          emissiveIntensity={0.4}
          transparent
          opacity={0.25}
        />
      </mesh>
      <mesh ref={wireRef}>
        <torusKnotGeometry args={[1.45, 0.48, 120, 16]} />
        <meshBasicMaterial
          color="#FFB000"
          wireframe
          transparent
          opacity={0.5}
        />
      </mesh>
    </group>
  )
}

function Particles() {
  const count = 400
  const positions = useMemo(() => {
    const pos = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const r = 3 + Math.random() * 4
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      pos[i*3] = r * Math.sin(phi) * Math.cos(theta)
      pos[i*3+1] = r * Math.sin(phi) * Math.sin(theta)
      pos[i*3+2] = r * Math.cos(phi)
    }
    return pos
  }, [])

  const ref = useRef<THREE.Points>(null)
  useFrame((_, delta) => {
    if (ref.current) ref.current.rotation.y += delta * 0.02
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.04}
        color="#FFD866"
        transparent
        opacity={0.6}
        sizeAttenuation
      />
    </points>
  )
}

function GridFloor() {
  return (
    <gridHelper
      args={[12, 24, '#FFB000', '#3A2800']}
      position={[0, -2.2, 0]}
    />
  )
}

export default function Hero3D() {
  return (
    <Canvas
      camera={{ position: [0, 0.5, 4.5], fov: 50 }}
      gl={{ antialias: true, alpha: true }}
      style={{ width: '100%', height: '100%' }}
    >
      <color attach="background" args={['#090806']} />
      <ambientLight intensity={0.2} />
      <pointLight position={[5, 5, 5]} intensity={1.5} color="#FFB000" />
      <pointLight position={[-3, 2, -3]} intensity={0.8} color="#00E5FF" />
      <TorusKnot />
      <Particles />
      <GridFloor />
      <OrbitControls enableZoom={false} enablePan={false} autoRotate={false} />
    </Canvas>
  )
}
