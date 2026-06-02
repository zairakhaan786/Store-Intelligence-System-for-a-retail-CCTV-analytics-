import { useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { Text, Html } from '@react-three/drei'
import useStore from '../store'

// ── Store Floor & Walls ───────────────────────────────────────────────────────
function StoreStructure() {
  return (
    <group>
      {/* Floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.05, 0]} receiveShadow>
        <planeGeometry args={[12, 14]} />
        <meshStandardMaterial color="#0f1117" roughness={0.8} metalness={0.1} />
      </mesh>

      {/* Grid overlay on floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.04, 0]}>
        <planeGeometry args={[12, 14]} />
        <meshBasicMaterial color="#1e293b" wireframe={true} opacity={0.3} transparent />
      </mesh>

      {/* Front wall */}
      <mesh position={[0, 2, 5.5]}>
        <boxGeometry args={[12, 4, 0.1]} />
        <meshStandardMaterial color="#0a0f1a" transparent opacity={0.7} />
      </mesh>

      {/* Back wall */}
      <mesh position={[0, 2, -5.5]}>
        <boxGeometry args={[12, 4, 0.1]} />
        <meshStandardMaterial color="#0a0f1a" transparent opacity={0.7} />
      </mesh>

      {/* Left wall */}
      <mesh position={[-6, 2, 0]}>
        <boxGeometry args={[0.1, 4, 14]} />
        <meshStandardMaterial color="#0a0f1a" transparent opacity={0.5} />
      </mesh>

      {/* Right wall */}
      <mesh position={[6, 2, 0]}>
        <boxGeometry args={[0.1, 4, 14]} />
        <meshStandardMaterial color="#0a0f1a" transparent opacity={0.5} />
      </mesh>

      {/* Ceiling lights */}
      {[-3, 0, 3].map((x) =>
        [-2, 0, 2].map((z) => (
          <pointLight key={`${x}-${z}`} position={[x, 3.5, z]} intensity={0.4} color="#e0e8ff" />
        ))
      )}
    </group>
  )
}

// ── Zone Box ──────────────────────────────────────────────────────────────────
function ZoneBox({ zone, occupancyData }) {
  const meshRef = useRef()
  const [hovered, setHovered] = useState(false)
  const { setSelectedZone, selectedZone, showLabels } = useStore()

  const occ = occupancyData?.find(z => z.zone_id === zone.id)
  const count = occ?.current_count || 0
  const capacity = occ?.capacity || 10
  const utilPct = Math.min(count / capacity, 1)

  // Color based on utilization
  const getColor = () => {
    if (utilPct > 0.8) return '#ef4444'      // red: overcrowded
    if (utilPct > 0.5) return '#f59e0b'      // amber: moderate
    return zone.color                          // default zone color
  }

  const height = Math.max(0.05, utilPct * 1.5) // height shows occupancy

  // Pulse animation for active zones
  useFrame((state) => {
    if (meshRef.current && count > 0) {
      meshRef.current.material.emissiveIntensity =
        0.2 + 0.1 * Math.sin(state.clock.elapsedTime * 2 + zone.pos[2])
    }
  })

  const isSelected = selectedZone === zone.id

  return (
    <group
      position={zone.pos}
      onClick={() => setSelectedZone(isSelected ? null : zone.id)}
      onPointerOver={() => setHovered(true)}
      onPointerOut={() => setHovered(false)}
    >
      {/* Zone floor plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
        <planeGeometry args={zone.size} />
        <meshStandardMaterial
          color={getColor()}
          transparent
          opacity={0.15 + (hovered ? 0.1 : 0)}
          emissive={getColor()}
          emissiveIntensity={0.05}
        />
      </mesh>

      {/* Occupancy bar (height = people count) */}
      {count > 0 && (
        <mesh ref={meshRef} position={[0, height / 2, 0]}>
          <boxGeometry args={[zone.size[0] * 0.9, height, zone.size[1] * 0.9]} />
          <meshStandardMaterial
            color={getColor()}
            transparent
            opacity={0.25}
            emissive={getColor()}
            emissiveIntensity={0.2}
            wireframe={false}
          />
        </mesh>
      )}

      {/* Wireframe outline */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
        <planeGeometry args={zone.size} />
        <meshBasicMaterial color={getColor()} wireframe transparent opacity={0.6} />
      </mesh>

      {/* Zone label */}
      {showLabels && (
        <Text
          position={[0, 0.3, 0]}
          fontSize={0.18}
          color={getColor()}
          anchorX="center"
          anchorY="middle"
          font="/fonts/inter.ttf"
        >
          {zone.label}
        </Text>
      )}

      {/* Count label */}
      {count > 0 && (
        <Text
          position={[0, height + 0.3, 0]}
          fontSize={0.25}
          color="#ffffff"
          anchorX="center"
        >
          {count} 👤
        </Text>
      )}

      {/* Info popup on hover */}
      {(hovered || isSelected) && (
        <Html position={[0, 1.5, 0]} center distanceFactor={6}>
          <div style={{
            background: 'rgba(10,15,30,0.9)',
            border: `1px solid ${getColor()}`,
            borderRadius: '12px',
            padding: '12px 16px',
            minWidth: '160px',
            backdropFilter: 'blur(20px)',
            color: '#e2e8f0',
            fontSize: '13px',
            fontFamily: 'Inter, sans-serif',
          }}>
            <div style={{ color: getColor(), fontWeight: 700, marginBottom: 6 }}>
              {zone.label}
            </div>
            <div>👥 {count} / {capacity} people</div>
            <div>📊 {Math.round(utilPct * 100)}% utilization</div>
            <div style={{ color: zone.type === 'checkout' ? '#f59e0b' : '#94a3b8', marginTop: 4 }}>
              Type: {zone.type}
            </div>
          </div>
        </Html>
      )}
    </group>
  )
}

// ── Animated Person Bubble ────────────────────────────────────────────────────
function PersonBubble({ position, color = '#a78bfa', trackId }) {
  const ref = useRef()
  useFrame((state) => {
    if (ref.current) {
      ref.current.position.y = 0.3 + Math.sin(state.clock.elapsedTime * 2 + parseInt(trackId || 0)) * 0.05
    }
  })
  return (
    <mesh ref={ref} position={position} castShadow>
      <sphereGeometry args={[0.15, 16, 16]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.4}
        roughness={0.2}
        metalness={0.5}
      />
    </mesh>
  )
}

// ── Event Particle ────────────────────────────────────────────────────────────
function EventParticle({ event }) {
  const ref = useRef()
  const startTime = useRef(Date.now())

  const zonePositions = {
    ENTRY_MAIN: [0, 0.5, 4], AISLE_A: [-2, 0.5, 1], AISLE_B: [2, 0.5, 1],
    BEAUTY_BAR: [0, 0.5, -1], CHECKOUT: [0, 0.5, -3.5], EXIT_MAIN: [0, 0.5, -5],
  }

  const pos = zonePositions[event.zone_id] || [0, 0.5, 0]
  const color = {
    entry: '#10b981', exit: '#ef4444', reentry: '#f59e0b',
    group_entry: '#06b6d4', anomaly: '#f472b6', zone_enter: '#a78bfa',
  }[event.event_type] || '#ffffff'

  useFrame(() => {
    if (ref.current) {
      const age = (Date.now() - startTime.current) / 1000
      ref.current.scale.setScalar(Math.max(0, 1 - age * 0.5))
      ref.current.position.y = pos[1] + age * 0.5
    }
  })

  return (
    <mesh ref={ref} position={pos}>
      <sphereGeometry args={[0.08, 8, 8]} />
      <meshBasicMaterial color={color} />
    </mesh>
  )
}

export { StoreStructure, ZoneBox, PersonBubble, EventParticle }
