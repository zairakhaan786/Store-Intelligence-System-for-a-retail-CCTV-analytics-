/**
 * HUD — Heads Up Display panels overlaid on the 3D scene.
 * Shows live KPIs, event log, anomaly alerts, and controls.
 */
import { motion, AnimatePresence } from 'framer-motion'
import useStore from '../store'

const SEVERITY_COLORS = {
  critical: '#ef4444', high: '#f97316', medium: '#f59e0b', low: '#10b981'
}

const EVENT_ICONS = {
  entry: '🟢', exit: '🔴', reentry: '🔁', group_entry: '👥',
  zone_enter: '🟣', zone_exit: '⚫', anomaly: '⚠️'
}

// ── Top Header Bar ─────────────────────────────────────────────────────────────
export function TopBar() {
  const { lastUpdated, loading, error } = useStore()
  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '12px 24px',
      background: 'rgba(3,7,18,0.8)',
      borderBottom: '1px solid rgba(124,58,237,0.3)',
      backdropFilter: 'blur(20px)',
      zIndex: 100,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ fontSize: 20 }}>🛍️</div>
        <div>
          <div className="orbitron" style={{ color: '#a78bfa', fontWeight: 700, fontSize: 14 }}>
            STORE INTELLIGENCE
          </div>
          <div style={{ color: '#64748b', fontSize: 11 }}>AI Store Intelligence System</div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div className="pulse" style={{
            width: 8, height: 8, borderRadius: '50%',
            background: error ? '#ef4444' : loading ? '#f59e0b' : '#10b981'
          }} />
          <span style={{ color: '#94a3b8', fontSize: 12 }}>
            {error ? 'API Error' : loading ? 'Updating...' : 'Live'}
          </span>
        </div>
        <div style={{ color: '#64748b', fontSize: 11 }}>
          Updated: {lastUpdated || '—'}
        </div>
      </div>
    </div>
  )
}

// ── Left KPI Panel ────────────────────────────────────────────────────────────
export function MetricsPanel() {
  const { metrics } = useStore()

  const kpis = [
    { label: 'Total Entries', value: metrics.total_entries, icon: '👥', color: '#10b981' },
    { label: 'Unique Visitors', value: metrics.unique_visitors, icon: '🔑', color: '#a78bfa' },
    { label: 'Active Now', value: metrics.active_sessions, icon: '🏃', color: '#06b6d4' },
    { label: 'Conversion', value: `${(metrics.conversion_rate * 100).toFixed(1)}%`, icon: '💰', color: '#f59e0b' },
    { label: 'Avg Dwell', value: `${Math.round(metrics.avg_dwell_seconds / 60)}m`, icon: '⏱️', color: '#c4b5fd' },
    { label: 'Anomalies', value: metrics.anomaly_count, icon: '⚠️', color: metrics.anomaly_count > 0 ? '#ef4444' : '#64748b' },
    { label: 'Re-entries', value: metrics.reentry_count, icon: '🔁', color: '#f97316' },
    { label: 'Group Entry', value: metrics.group_entry_count, icon: '👨‍👩‍👦', color: '#60a5fa' },
  ]

  return (
    <motion.div
      initial={{ x: -100, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      style={{
        position: 'fixed', top: 70, left: 20,
        width: 220,
        background: 'rgba(3,7,18,0.85)',
        border: '1px solid rgba(124,58,237,0.4)',
        borderRadius: 16,
        padding: 16,
        backdropFilter: 'blur(20px)',
        zIndex: 90,
      }}
    >
      <div className="orbitron" style={{ color: '#a78bfa', fontSize: 11, marginBottom: 12, letterSpacing: '0.1em' }}>
        ◈ LIVE METRICS
      </div>
      {kpis.map((kpi) => (
        <div key={kpi.label} style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '6px 0',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
        }}>
          <div style={{ color: '#94a3b8', fontSize: 12 }}>
            {kpi.icon} {kpi.label}
          </div>
          <div style={{ color: kpi.color, fontWeight: 700, fontSize: 14, fontFamily: 'Orbitron, monospace' }}>
            {kpi.value}
          </div>
        </div>
      ))}
    </motion.div>
  )
}

// ── Right Event Feed ──────────────────────────────────────────────────────────
export function EventFeed() {
  const { events } = useStore()
  const recent = [...events].slice(0, 10)

  return (
    <motion.div
      initial={{ x: 100, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      style={{
        position: 'fixed', top: 70, right: 20,
        width: 260,
        background: 'rgba(3,7,18,0.85)',
        border: '1px solid rgba(124,58,237,0.4)',
        borderRadius: 16,
        padding: 16,
        backdropFilter: 'blur(20px)',
        zIndex: 90,
        maxHeight: '60vh',
        overflow: 'hidden',
      }}
    >
      <div className="orbitron" style={{ color: '#a78bfa', fontSize: 11, marginBottom: 12, letterSpacing: '0.1em' }}>
        ◈ LIVE EVENT STREAM
      </div>
      <div style={{ overflowY: 'auto', maxHeight: 'calc(60vh - 50px)' }}>
        <AnimatePresence>
          {recent.map((ev, i) => (
            <motion.div
              key={ev.id || i}
              initial={{ x: 20, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ opacity: 0 }}
              style={{
                padding: '6px 8px',
                marginBottom: 4,
                background: 'rgba(255,255,255,0.03)',
                borderRadius: 8,
                borderLeft: `3px solid ${
                  ev.event_type === 'entry' ? '#10b981' :
                  ev.event_type === 'exit' ? '#ef4444' :
                  ev.event_type === 'anomaly' ? '#f472b6' :
                  ev.event_type === 'reentry' ? '#f59e0b' : '#a78bfa'
                }`,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 12, color: '#e2e8f0' }}>
                  {EVENT_ICONS[ev.event_type] || '⚪'} {ev.event_type?.toUpperCase()}
                </span>
                <span style={{ fontSize: 10, color: '#475569' }}>
                  T:{ev.track_id?.slice(0, 6)}
                </span>
              </div>
              <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>
                📍 {ev.zone_id || 'Unknown Zone'}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        {recent.length === 0 && (
          <div style={{ color: '#475569', fontSize: 12, textAlign: 'center', padding: 20 }}>
            No events yet
          </div>
        )}
      </div>
    </motion.div>
  )
}

// ── Bottom Anomaly Alert Bar ──────────────────────────────────────────────────
export function AnomalyAlerts() {
  const { anomalies } = useStore()
  const active = anomalies.filter(a => a.is_active).slice(0, 5)

  if (active.length === 0) return null

  return (
    <motion.div
      initial={{ y: 100, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      style={{
        position: 'fixed', bottom: 20, left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex', gap: 10,
        zIndex: 90,
      }}
    >
      {active.map((a, i) => (
        <motion.div
          key={a.id || i}
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          style={{
            background: `rgba(${a.severity === 'high' ? '239,68,68' : '245,158,11'},0.15)`,
            border: `1px solid ${SEVERITY_COLORS[a.severity] || '#f59e0b'}`,
            borderRadius: 10,
            padding: '8px 14px',
            backdropFilter: 'blur(20px)',
            display: 'flex', alignItems: 'center', gap: 8,
          }}
        >
          <div className="pulse" style={{
            width: 8, height: 8, borderRadius: '50%',
            background: SEVERITY_COLORS[a.severity] || '#f59e0b'
          }} />
          <div>
            <div style={{ color: '#f1f5f9', fontSize: 12, fontWeight: 600 }}>
              ⚠️ {a.anomaly_type?.toUpperCase() || 'ALERT'}
            </div>
            <div style={{ color: '#94a3b8', fontSize: 10 }}>
              {a.zone_id || 'Store'} • {a.severity}
            </div>
          </div>
        </motion.div>
      ))}
    </motion.div>
  )
}

// ── Camera Mode Controls ──────────────────────────────────────────────────────
export function CameraControls() {
  const { cameraMode, setCameraMode, showLabels } = useStore()
  const modes = ['orbit', 'top', 'fly']

  return (
    <motion.div
      initial={{ y: -50, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      style={{
        position: 'fixed', top: 70, left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex', gap: 8,
        zIndex: 90,
      }}
    >
      {modes.map(mode => (
        <button
          key={mode}
          onClick={() => setCameraMode(mode)}
          style={{
            background: cameraMode === mode ? 'rgba(124,58,237,0.4)' : 'rgba(3,7,18,0.8)',
            border: `1px solid ${cameraMode === mode ? '#7c3aed' : 'rgba(255,255,255,0.1)'}`,
            borderRadius: 8, padding: '6px 14px', color: '#e2e8f0',
            cursor: 'pointer', fontSize: 12,
            backdropFilter: 'blur(10px)',
            fontFamily: 'Orbitron, monospace',
            textTransform: 'uppercase', letterSpacing: '0.05em',
          }}
        >
          {mode === 'orbit' ? '🌐' : mode === 'top' ? '🗺️' : '✈️'} {mode}
        </button>
      ))}
    </motion.div>
  )
}
