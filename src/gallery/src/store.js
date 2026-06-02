import { create } from 'zustand'

// Store zones for 3D visualization
export const ZONES = [
  { id: 'ENTRY_MAIN', label: 'Main Entrance', type: 'entry',
    pos: [0, 0, 4], size: [6, 0.1, 2], color: '#10b981' },
  { id: 'AISLE_A',    label: 'Aisle A – Skincare', type: 'aisle',
    pos: [-2, 0, 1], size: [2.5, 0.1, 2.5], color: '#a78bfa' },
  { id: 'AISLE_B',    label: 'Aisle B – Makeup', type: 'aisle',
    pos: [2, 0, 1],  size: [2.5, 0.1, 2.5], color: '#c4b5fd' },
  { id: 'BEAUTY_BAR', label: 'Beauty Bar', type: 'beauty_bar',
    pos: [0, 0, -1], size: [3.5, 0.1, 2],   color: '#f472b6' },
  { id: 'CHECKOUT',   label: 'Checkout Counter', type: 'checkout',
    pos: [0, 0, -3.5], size: [5, 0.1, 1.5],  color: '#f59e0b' },
  { id: 'EXIT_MAIN',  label: 'Main Exit', type: 'exit',
    pos: [0, 0, -5], size: [6, 0.1, 1],      color: '#ef4444' },
]

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const useStore = create((set, get) => ({
  // Metrics
  metrics: {
    total_entries: 0, unique_visitors: 0, avg_dwell_seconds: 0,
    conversion_rate: 0, active_sessions: 0, anomaly_count: 0,
    group_entry_count: 0, reentry_count: 0,
  },
  occupancy: [],
  events: [],
  anomalies: [],
  lastUpdated: null,
  loading: false,
  error: null,

  // UI state
  selectedZone: null,
  cameraMode: 'orbit',  // orbit | fly | top
  showLabels: true,
  showPaths: true,

  // Gesture state
  activeGesture: null,

  // Actions
  setSelectedZone: (zone) => set({ selectedZone: zone }),
  setCameraMode: (mode) => set({ cameraMode: mode }),
  setActiveGesture: (gesture) => set({ activeGesture: gesture }),

  fetchAll: async () => {
    set({ loading: true })
    try {
      const [metricsRes, occupancyRes, eventsRes, anomaliesRes] = await Promise.all([
        fetch(`${API_BASE}/metrics`),
        fetch(`${API_BASE}/metrics/occupancy`),
        fetch(`${API_BASE}/events?page_size=20`),
        fetch(`${API_BASE}/anomalies`),
      ])

      const metrics    = metricsRes.ok    ? await metricsRes.json()    : get().metrics
      const occupancy  = occupancyRes.ok  ? await occupancyRes.json()  : { zones: [] }
      const eventsData = eventsRes.ok     ? await eventsRes.json()     : { events: [] }
      const anomalyData = anomaliesRes.ok ? await anomaliesRes.json()  : { anomalies: [] }

      set({
        metrics,
        occupancy: occupancy.zones || [],
        events: eventsData.events || [],
        anomalies: anomalyData.anomalies || [],
        lastUpdated: new Date().toLocaleTimeString(),
        loading: false,
        error: null,
      })
    } catch (err) {
      set({ error: err.message, loading: false })
    }
  },
}))

export default useStore
