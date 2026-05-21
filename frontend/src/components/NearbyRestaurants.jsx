import React, { useState, useEffect, useRef, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap, Circle } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { MapPin, Navigation, Search, RefreshCw, UtensilsCrossed, Phone, Globe, Clock, AlertCircle, Loader2 } from 'lucide-react';

// ---------------------------------------------------------------------------
// Leaflet icon fix (Vite / webpack asset pipeline strips default images)
// ---------------------------------------------------------------------------
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl:       'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl:     'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

// Custom coloured markers
const makeIcon = (color) =>
  new L.DivIcon({
    className: '',
    html: `
      <div style="
        width:32px;height:40px;
        background:${color};
        border-radius:50% 50% 50% 0;
        transform:rotate(-45deg);
        border:3px solid white;
        box-shadow:0 4px 15px rgba(0,0,0,.35);
      ">
        <div style="
          width:10px;height:10px;
          background:white;
          border-radius:50%;
          position:absolute;top:50%;left:50%;
          transform:translate(-50%,-50%) rotate(45deg);
        "></div>
      </div>`,
    iconSize:   [32, 40],
    iconAnchor: [16, 40],
    popupAnchor:[0, -44],
  });

const userIcon       = makeIcon('#3b82f6');  // blue  – "you are here"
const restaurantIcon = makeIcon('#ff6b00');  // orange – restaurant

// ---------------------------------------------------------------------------
// Map auto-fit helper
// ---------------------------------------------------------------------------
function FitBounds({ userPos, restaurants }) {
  const map = useMap();
  useEffect(() => {
    if (!userPos) return;
    const points = [[userPos.lat, userPos.lng]];
    restaurants.forEach(r => points.push([r.lat, r.lng]));
    if (points.length > 1) {
      map.fitBounds(L.latLngBounds(points), { padding: [40, 40] });
    } else {
      map.setView([userPos.lat, userPos.lng], 14);
    }
  }, [userPos, restaurants, map]);
  return null;
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
export default function NearbyRestaurants() {
  const [userPos,      setUserPos]      = useState(null);
  const [restaurants,  setRestaurants]  = useState([]);
  const [loading,      setLoading]      = useState(false);
  const [gpsLoading,   setGpsLoading]   = useState(false);
  const [error,        setError]        = useState('');
  const [radius,       setRadius]       = useState(8000);
  const [limit,        setLimit]        = useState(20);
  const [selected,     setSelected]     = useState(null);
  const [searchTerm,   setSearchTerm]   = useState('');
  const listRef = useRef(null);

  // -------------------------------------------------------------------------
  // GPS detection
  // -------------------------------------------------------------------------
  const detectLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setError('Geolocation is not supported by your browser.');
      return;
    }
    setGpsLoading(true);
    setError('');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        // console.log('[GPS] Real coordinates detected:', lat, lng);
        setUserPos({ lat, lng });
        setGpsLoading(false);
      },
      () => {
        setError('Unable to retrieve your location. Please allow location access.');
        setGpsLoading(false);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }, []);

  // Auto-detect on mount
  useEffect(() => { detectLocation(); }, [detectLocation]);

  // -------------------------------------------------------------------------
  // Fetch restaurants whenever userPos / radius / limit changes
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!userPos) return;
    fetchNearby();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userPos, radius, limit]);

  const fetchNearby = async () => {
    if (!userPos) return;
    setLoading(true);
    setError('');
    try {
      const response = await apiClient.get('/api/restaurants/nearby', {
        params: {
          lat: userPos.lat,
          lng: userPos.lng,
          radius: radius,
          limit: limit,
        }
      });
      
      const data = response?.success ? (response.data || []) : (Array.isArray(response) ? response : []);
      setRestaurants(data);
      if (data.length === 0) setError('No restaurants found in this area. Try increasing the radius.');
    } catch (err) {
      if (err?.silent) return;
      setError(err.detail || err.message || 'Failed to fetch nearby restaurants.');
      setRestaurants([]);
    } finally {
      setLoading(false);
    }
  };

  // -------------------------------------------------------------------------
  // Filtered list
  // -------------------------------------------------------------------------
  const filtered = restaurants.filter(r =>
    r.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (r.cuisine && r.cuisine.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  // -------------------------------------------------------------------------
  // Scroll selected card into view
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (selected !== null && listRef.current) {
      const card = listRef.current.querySelector(`[data-id="${selected}"]`);
      card?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [selected]);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <div style={styles.page}>
      {/* ── Header ─────────────────────────────────────────── */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <div style={styles.headerIcon}>
            <UtensilsCrossed size={24} color="white" />
          </div>
          <div>
            <h1 style={styles.title}>Nearby Restaurants</h1>
            <p style={styles.subtitle}>Real-time discovery powered by OpenStreetMap</p>
          </div>
        </div>

        <div style={styles.controls}>
          {/* Radius selector */}
          <div style={styles.controlGroup}>
            <label style={styles.label}>Radius</label>
            <select
              value={radius}
              onChange={e => setRadius(Number(e.target.value))}
              style={styles.select}
            >
              {[1000, 2000, 3000, 5000, 8000, 10000, 15000].map(r => (
                <option key={r} value={r}>{r >= 1000 ? `${r / 1000} km` : `${r} m`}</option>
              ))}
            </select>
          </div>

          {/* Limit selector */}
          <div style={styles.controlGroup}>
            <label style={styles.label}>Results</label>
            <select
              value={limit}
              onChange={e => setLimit(Number(e.target.value))}
              style={styles.select}
            >
              {[10, 20, 30, 50].map(l => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>

          {/* Detect / Refresh */}
          <button
            onClick={detectLocation}
            disabled={gpsLoading}
            style={{ ...styles.btn, ...styles.btnSecondary }}
            title="Re-detect my location"
          >
            {gpsLoading ? <Loader2 size={16} style={styles.spin} /> : <Navigation size={16} />}
            {gpsLoading ? 'Locating…' : 'My Location'}
          </button>

          <button
            onClick={fetchNearby}
            disabled={loading || !userPos}
            style={{ ...styles.btn, ...styles.btnPrimary }}
          >
            {loading ? <Loader2 size={16} style={styles.spin} /> : <RefreshCw size={16} />}
            {loading ? 'Searching…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* ── Error banner ───────────────────────────────────── */}
      {error && (
        <div style={styles.errorBanner}>
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* ── Status strip ───────────────────────────────────── */}
      {userPos && (
        <div style={styles.statusStrip}>
          <MapPin size={14} color="#ff6b00" />
          <span>
            Your location: <strong>{userPos.lat.toFixed(5)}, {userPos.lng.toFixed(5)}</strong>
            &nbsp;·&nbsp;
            {loading
              ? 'Fetching restaurants…'
              : <><strong>{filtered.length}</strong> restaurant{filtered.length !== 1 ? 's' : ''} found</>
            }
          </span>
        </div>
      )}

      {/* ── Main layout: map + list ────────────────────────── */}
      <div style={styles.layout} className="relative z-0">

        {/* MAP */}
        <div style={styles.mapWrapper}>
          {userPos ? (
            <MapContainer
              center={[userPos.lat, userPos.lng]}
              zoom={14}
              style={{ width: '100%', height: '100%' }}
              zoomControl={true}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              {/* Radius ring */}
              <Circle
                center={[userPos.lat, userPos.lng]}
                radius={radius}
                pathOptions={{ color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.06, weight: 1.5, dashArray: '6 4' }}
              />

              {/* User marker */}
              <Marker position={[userPos.lat, userPos.lng]} icon={userIcon}>
                <Popup>
                  <div style={{ textAlign: 'center', fontWeight: 700 }}>📍 You are here</div>
                </Popup>
              </Marker>

              {/* Restaurant markers */}
              {filtered.map(r => (
                <Marker
                  key={r.id}
                  position={[r.lat, r.lng]}
                  icon={restaurantIcon}
                  eventHandlers={{ click: () => setSelected(r.id) }}
                >
                  <Popup>
                    <div style={{ minWidth: 160 }}>
                      <div style={{ fontWeight: 700, color: '#ff6b00', marginBottom: 4 }}>{r.name}</div>
                      {r.cuisine && <div style={{ fontSize: 12, color: '#666' }}>🍽 {r.cuisine}</div>}
                      <div style={{ fontSize: 12, color: '#444', marginTop: 4 }}>
                        📏 {r.distance_km < 1
                          ? `${Math.round(r.distance_km * 1000)} m away`
                          : `${r.distance_km.toFixed(2)} km away`}
                      </div>
                      {r.opening_hours && <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>🕐 {r.opening_hours}</div>}
                    </div>
                  </Popup>
                </Marker>
              ))}

              <FitBounds userPos={userPos} restaurants={filtered} />
            </MapContainer>
          ) : (
            <div style={styles.mapPlaceholder}>
              {gpsLoading
                ? <><Loader2 size={40} color="#ff6b00" style={styles.spin} /><p>Detecting your location…</p></>
                : <><MapPin size={40} color="#ff6b00" /><p>Allow location access to see the map</p><button onClick={detectLocation} style={{ ...styles.btn, ...styles.btnPrimary, marginTop: 12 }}>Enable Location</button></>
              }
            </div>
          )}
        </div>

        {/* LIST */}
        <div style={styles.listPanel} ref={listRef}>
          {/* Search */}
          <div style={styles.searchWrapper}>
            <Search size={16} color="#999" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)' }} />
            <input
              type="text"
              placeholder="Search by name or cuisine…"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              style={styles.searchInput}
            />
          </div>

          {/* Loading skeleton */}
          {loading && restaurants.length === 0 && (
            Array.from({ length: 5 }).map((_, i) => (
              <div key={i} style={styles.skeleton}>
                <div style={{ ...styles.skeletonLine, width: '60%' }} />
                <div style={{ ...styles.skeletonLine, width: '40%', height: 10, marginTop: 8 }} />
              </div>
            ))
          )}

          {/* Restaurant cards */}
          {filtered.map((r, idx) => (
            <div
              key={r.id}
              data-id={r.id}
              onClick={() => setSelected(selected === r.id ? null : r.id)}
              style={{
                ...styles.card,
                ...(selected === r.id ? styles.cardSelected : {}),
              }}
            >
              {/* Rank badge */}
              <div style={styles.rank}>#{idx + 1}</div>

              <div style={styles.cardBody}>
                <div style={styles.cardHeader}>
                  <div>
                    <h3 style={styles.restName}>{r.name}</h3>
                    {r.cuisine && (
                      <span style={styles.cuisineBadge}>{r.cuisine.replace(/;/g, ' · ')}</span>
                    )}
                  </div>
                  <div style={styles.distanceBadge}>
                    {r.distance_km < 1
                      ? `${Math.round(r.distance_km * 1000)} m`
                      : `${r.distance_km.toFixed(2)} km`}
                  </div>
                </div>

                {/* Expanded details */}
                {selected === r.id && (
                  <div style={styles.cardDetails}>
                    {r.opening_hours && (
                      <div style={styles.detailRow}>
                        <Clock size={13} color="#ff6b00" />
                        <span>{r.opening_hours}</span>
                      </div>
                    )}
                    {r.phone && (
                      <div style={styles.detailRow}>
                        <Phone size={13} color="#ff6b00" />
                        <a href={`tel:${r.phone}`} style={styles.detailLink}>{r.phone}</a>
                      </div>
                    )}
                    {r.website && (
                      <div style={styles.detailRow}>
                        <Globe size={13} color="#ff6b00" />
                        <a href={r.website} target="_blank" rel="noopener noreferrer" style={styles.detailLink}>
                          {r.website.replace(/^https?:\/\//, '')}
                        </a>
                      </div>
                    )}
                    <div style={styles.detailRow}>
                      <MapPin size={13} color="#ff6b00" />
                      <span>{r.lat.toFixed(5)}, {r.lng.toFixed(5)}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}

          {!loading && filtered.length === 0 && restaurants.length > 0 && (
            <div style={styles.emptyState}>
              <Search size={36} color="#ddd" />
              <p>No results match "<strong>{searchTerm}</strong>"</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles (inline — no extra CSS files needed)
// ---------------------------------------------------------------------------
const styles = {
  page: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg,#0f0f1a 0%,#1a0a00 100%)',
    color: '#e2e8f0',
    fontFamily: "'Inter', sans-serif",
    paddingTop: 80,   /* ← clears sticky navbar (80px tall) */
    paddingBottom: 40,
    position: 'relative',
    zIndex: 0,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 16,
    padding: '28px 32px 20px',
    borderBottom: '1px solid rgba(255,255,255,.07)',
    background: 'rgba(0,0,0,.35)',
    backdropFilter: 'blur(12px)',
  },
  headerLeft: { display: 'flex', alignItems: 'center', gap: 16 },
  headerIcon: {
    width: 52, height: 52, borderRadius: 14,
    background: 'linear-gradient(135deg,#ff6b00,#ff9500)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 8px 24px rgba(255,107,0,.35)',
  },
  title:    { margin: 0, fontSize: 24, fontWeight: 800, color: '#fff' },
  subtitle: { margin: '2px 0 0', fontSize: 13, color: '#94a3b8' },
  controls: { display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' },
  controlGroup: { display: 'flex', flexDirection: 'column', gap: 4 },
  label: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '.06em' },
  select: {
    background: 'rgba(255,255,255,.08)', border: '1px solid rgba(255,255,255,.15)',
    color: '#e2e8f0', borderRadius: 8, padding: '7px 12px', fontSize: 14, cursor: 'pointer',
    outline: 'none',
  },
  btn: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px',
    borderRadius: 10, border: 'none', cursor: 'pointer', fontSize: 14,
    fontWeight: 600, transition: 'all .2s',
  },
  btnPrimary: {
    background: 'linear-gradient(135deg,#ff6b00,#ff9500)',
    color: '#fff', boxShadow: '0 4px 14px rgba(255,107,0,.4)',
  },
  btnSecondary: {
    background: 'rgba(255,255,255,.1)',
    color: '#e2e8f0', border: '1px solid rgba(255,255,255,.15)',
  },
  spin: { animation: 'spin 1s linear infinite' },
  errorBanner: {
    display: 'flex', alignItems: 'center', gap: 8,
    margin: '12px 32px', padding: '12px 16px',
    background: 'rgba(239,68,68,.15)', border: '1px solid rgba(239,68,68,.35)',
    borderRadius: 10, color: '#fca5a5', fontSize: 14,
  },
  statusStrip: {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '10px 32px', fontSize: 13, color: '#94a3b8',
    borderBottom: '1px solid rgba(255,255,255,.05)',
  },
  layout: {
    display: 'grid',
    gridTemplateColumns: '1fr 380px',
    gap: 0,
    /* Fixed height — never stretches to full viewport */
    height: 520,
    minHeight: 400,
    maxHeight: '70vh',
    overflow: 'hidden',
    position: 'relative',
    zIndex: 0,
  },
  mapWrapper: {
    position: 'relative',
    overflow: 'hidden',
    background: '#fff',   /* ← removes black background */
  },
  mapPlaceholder: {
    height: '100%', display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center',
    background: 'rgba(0,0,0,.2)', color: '#64748b', gap: 12, fontSize: 15,
  },
  listPanel: {
    overflowY: 'auto',
    borderLeft: '1px solid rgba(255,255,255,.07)',
    background: 'rgba(0,0,0,.25)',
    display: 'flex', flexDirection: 'column', gap: 0,
    padding: '12px 12px 20px',
  },
  searchWrapper: {
    position: 'relative', marginBottom: 12,
  },
  searchInput: {
    width: '100%', boxSizing: 'border-box',
    background: 'rgba(255,255,255,.07)', border: '1px solid rgba(255,255,255,.12)',
    borderRadius: 10, padding: '9px 12px 9px 36px',
    color: '#e2e8f0', fontSize: 13, outline: 'none',
  },
  card: {
    display: 'flex', gap: 10, alignItems: 'flex-start',
    padding: '12px 10px', borderRadius: 12, cursor: 'pointer',
    marginBottom: 6, transition: 'all .2s',
    border: '1px solid rgba(255,255,255,.06)',
    background: 'rgba(255,255,255,.04)',
  },
  cardSelected: {
    background: 'rgba(255,107,0,.12)',
    border: '1px solid rgba(255,107,0,.4)',
    boxShadow: '0 0 20px rgba(255,107,0,.15)',
  },
  rank: {
    minWidth: 26, height: 26, borderRadius: 6,
    background: 'rgba(255,107,0,.2)', color: '#ff6b00',
    fontSize: 11, fontWeight: 700,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    marginTop: 2,
  },
  cardBody: { flex: 1, minWidth: 0 },
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 },
  restName: { margin: 0, fontSize: 14, fontWeight: 700, color: '#f1f5f9', lineHeight: 1.3 },
  cuisineBadge: {
    display: 'inline-block', marginTop: 4, fontSize: 11,
    background: 'rgba(255,107,0,.18)', color: '#ff9500',
    borderRadius: 4, padding: '1px 6px', fontWeight: 500,
  },
  distanceBadge: {
    fontSize: 12, fontWeight: 700, color: '#ff6b00',
    background: 'rgba(255,107,0,.12)', borderRadius: 6,
    padding: '2px 8px', whiteSpace: 'nowrap',
  },
  cardDetails: {
    marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6,
    paddingTop: 8, borderTop: '1px solid rgba(255,255,255,.08)',
  },
  detailRow: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#94a3b8' },
  detailLink: { color: '#60a5fa', textDecoration: 'none', wordBreak: 'break-all' },
  skeleton: {
    padding: '14px 10px', borderRadius: 12, marginBottom: 6,
    background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.06)',
  },
  skeletonLine: {
    height: 14, borderRadius: 4,
    background: 'linear-gradient(90deg,rgba(255,255,255,.06) 25%,rgba(255,255,255,.12) 50%,rgba(255,255,255,.06) 75%)',
    backgroundSize: '200% 100%',
    animation: 'shimmer 1.5s infinite',
  },
  emptyState: {
    textAlign: 'center', padding: 40, color: '#475569',
    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10,
  },
};

// Inject keyframe animations once
if (typeof document !== 'undefined' && !document.getElementById('nr-keyframes')) {
  const style = document.createElement('style');
  style.id = 'nr-keyframes';
  style.textContent = `
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes shimmer { to { background-position: -200% 0; } }
  `;
  document.head.appendChild(style);
}
