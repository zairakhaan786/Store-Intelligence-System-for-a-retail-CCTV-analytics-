/**
 * Main App — 3D Store Intelligence Gallery
 * Combines Three.js scene + React HUD + live API data
 */
import { useEffect, useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Stars, Grid, Environment, Float } from '@react-three/drei'
import { Toaster, toast } from 'react-hot-toast'
import { StoreStructure, ZoneBox, PersonBubble, EventParticle } from './components/StoreScene'
import { TopBar, MetricsPanel, EventFeed, AnomalyAlerts, CameraControls } from './components/HUD'
import useStore, { ZONES } from './store'

const POLL_INTERVAL = 8000  // ms

export default function App() {
  const { fetchAll, metrics, occupancy, events, anomalies, cameraMode } = useStore()
  const prevAnomalyCount = useRef(0)

  // Poll API every 8 seconds
  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [])

  // Toast on new anomalies
  useEffect(() => {
    if (anomalies.length > prevAnomalyCount.current) {
      const newAnomaly = anomalies[0]
      toast.error(`⚠️ ${newAnomaly?.anomaly_type?.toUpperCase() || 'Anomaly'} detected!`, {
        duration: 4000,
        style: {
          background: '#1a0a0a',
          border: '1px solid #ef4444',
          color: '#fca5a5',
        }
      })
    }
    prevAnomalyCount.current = anomalies.length
  }, [anomalies.length])

  // Camera position based on mode
  const cameraConfig = {
    orbit: { position: [8, 8, 10], fov: 55 },
    top:   { position: [0, 16, 0.1], fov: 60 },
    fly:   { position: [0, 3, 12], fov: 75 },
  }[cameraMode] || { position: [8, 8, 10], fov: 55 }

  // Recent event particles (last 5 events only)
  const recentEvents = events.slice(0, 5)

  return (
    <div style={{ width: '100vw', height: '100vh', background: '#030712' }}>
      {/* ── 3D Canvas ──────────────────────────────────────────── */}
      <Canvas
        camera={{ position: cameraConfig.position, fov: cameraConfig.fov }}
        shadows
        gl={{ antialias: true, alpha: true }}
        style={{ position: 'absolute', top: 0, left: 0 }}
      >
        {/* Lighting */}
        <ambientLight intensity={0.15} />
        <directionalLight position={[5, 10, 5]} intensity={0.5} castShadow />
        <pointLight position={[0, 8, 0]} intensity={0.3} color="#7c3aed" />
        <pointLight position={[-6, 3, 0]} intensity={0.2} color="#06b6d4" />
        <pointLight position={[6, 3, 0]} intensity={0.2} color="#a78bfa" />

        {/* Stars background */}
        <Stars radius={100} depth={50} count={2000} factor={3} saturation={0.5} fade />

        {/* Environment */}
        <fog attach="fog" args={['#030712', 15, 40]} />

        {/* Store Structure */}
        <StoreStructure />

        {/* Zone Boxes */}
        {ZONES.map(zone => (
          <ZoneBox key={zone.id} zone={zone} occupancyData={occupancy} />
        ))}

        {/* Floating person bubbles based on active sessions */}
        {Array.from({ length: Math.min(metrics.active_sessions || 0, 15) }).map((_, i) => {
          const zone = ZONES[i % ZONES.length]
          const offset = [(Math.random() - 0.5) * zone.size[0] * 0.6, 0, (Math.random() - 0.5) * zone.size[1] * 0.6]
          const pos = [zone.pos[0] + offset[0], 0.3, zone.pos[2] + offset[2]]
          return (
            <PersonBubble
              key={i}
              position={pos}
              trackId={String(i)}
              color={`hsl(${(i * 40) % 360}, 70%, 65%)`}
            />
          )
        })}

        {/* Event particles */}
        {recentEvents.map((ev, i) => (
          <EventParticle key={ev.id || i} event={ev} />
        ))}

        {/* Camera Controls */}
        {cameraMode === 'orbit' && (
          <OrbitControls
            enablePan={true}
            enableZoom={true}
            enableRotate={true}
            minDistance={5}
            maxDistance={25}
            maxPolarAngle={Math.PI / 2.1}
            target={[0, 0, 0]}
          />
        )}
        {cameraMode === 'top' && (
          <OrbitControls
            enablePan={true}
            enableZoom={true}
            enableRotate={false}
            target={[0, 0, 0]}
          />
        )}
      </Canvas>

      {/* ── 2D HUD Overlays ─────────────────────────────────── */}
      <TopBar />
      <MetricsPanel />
      <EventFeed />
      <AnomalyAlerts />
      <CameraControls />

      {/* ── Toast Notifications ──────────────────────────────── */}
      <Toaster position="bottom-right" />

      {/* ── Gesture hint ────────────────────────────────────── */}
      <div style={{
        position: 'fixed', bottom: 20, right: 20,
        background: 'rgba(3,7,18,0.8)',
        border: '1px solid rgba(124,58,237,0.3)',
        borderRadius: 12, padding: '8px 14px',
        fontSize: 11, color: '#64748b',
        backdropFilter: 'blur(10px)',
        zIndex: 80,
      }}>
        🖱️ Drag to orbit • Scroll to zoom • Click zones to inspect
      </div>
    </div>
  )
}
