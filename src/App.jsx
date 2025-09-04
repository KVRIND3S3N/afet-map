// @ts-nocheck
import { useCallback, useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, GeoJSON, Marker, Popup, Polyline, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

/** ========= Ayarlar ========= */
const DEFAULTS = {
  center: [38.42762, 27.13763],
  zoom: 11,
  burnAreasUrl: "/api/burn-areas",
  assemblyAreasUrl: "/api/assembly-areas",
  routeToFireUrl: "/api/route-to-fire",
  routeToAssemblyUrl: "/api/route-to-assembly",
};

// Şiddet renkleri (klasik mod)
const severityColors = {
  "Etkilenmemiş": "#D9D9D9",
  "Düşük": "#22c55e",
  "Orta-Düşük": "#f59e0b",
  "Orta-Yüksek": "#ef4444",
  "Yüksek": "#b91c1c",
};

/** ========= Marker ikon fix ========= */
const DefaultIcon = new L.Icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

/** ========= Yardımcılar (öncelik hesabı) ========= */
function haversineKm(a, b) {
  const R = 6371, toRad = d => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat), dLon = toRad(b.lon - a.lon);
  const s1 = Math.sin(dLat/2) ** 2;
  const s2 = Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon/2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s1 + s2));
}
function centroidOf(feature) {
  const g = feature?.geometry;
  if (!g) return null;
  if (g.type === "Point") return { lon: g.coordinates[0], lat: g.coordinates[1] };
  if (g.type === "Polygon") {
    const ring = g.coordinates?.[0]; if (!ring?.length) return null;
    let sx = 0, sy = 0; for (const [x, y] of ring) { sx += x; sy += y; }
    return { lon: sx / ring.length, lat: sy / ring.length };
  }
  if (g.type === "MultiPolygon") {
    const ring = g.coordinates?.[0]?.[0]; if (!ring?.length) return null;
    let sx = 0, sy = 0; for (const [x, y] of ring) { sx += x; sy += y; }
    return { lon: sx / ring.length, lat: sy / ring.length };
  }
  return null;
}
function severityWeight(label) {
  if (label === "Yüksek") return 5;
  if (label === "Orta-Yüksek") return 3;
  return 1;
}
function colorForPriority(score) {
  if (score >= 8) return "#4B0082";   // çok yüksek
  if (score >= 6) return "#FF0000";   // yüksek
  if (score >= 4) return "#FFA500";   // orta
  return "#FFFF00";                    // düşük
}

/** ========= Harita içi yardımcılar ========= */
function UseBboxFetcher({ enabled, onBoundsChange, debounceMs = 700 }) {
  const map = useMap();
  const tRef = useRef(null);
  useEffect(() => {
    if (!enabled) return;
    const fire = () => {
      const b = map.getBounds();
      onBoundsChange?.([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]);
    };
    fire();
    const onMoveEnd = () => {
      if (tRef.current) clearTimeout(tRef.current);
      tRef.current = setTimeout(fire, debounceMs);
    };
    map.on("moveend", onMoveEnd);
    return () => { map.off("moveend", onMoveEnd); if (tRef.current) clearTimeout(tRef.current); };
  }, [enabled, onBoundsChange, debounceMs, map]);
  return null;
}
function ClickToSelect({ onPoint }) {
  useMapEvents({ click(e) { onPoint?.({ lat: e.latlng.lat, lon: e.latlng.lng }); } });
  return null;
}

/** ========= UI parçaları (SIRIUS görünüm) ========= */
function BrandTopCenter({ clickPoint }) {
  return (
    <div style={{
      position: "absolute",
      top: 16,
      left: "50%",
      transform: "translateX(-50%)",
      color: "#fff",
      textAlign: "center",
      zIndex: 1000,
      pointerEvents: "none"
    }}>
      {/* Görsel */}
      <img
        src="/SIRIUS.png"   // public klasörüne koyacağız
        alt="SIRIUS"
        style={{ height: 50, objectFit: "contain", marginBottom: 4 }}
      />

      {/* Koordinatlar */}
      <div style={{ opacity: .8, fontSize: 12 }}>
        {clickPoint ? `${clickPoint.lat.toFixed(5)}, ${clickPoint.lon.toFixed(5)}` : "—"}
      </div>
    </div>
  );
}

function LeftToolbar() {
  const btn = {
    width: 36, height: 36, borderRadius: 10, background: "#23262d", color: "#fff",
    display: "flex", alignItems: "center", justifyContent: "center",
    boxShadow: "0 8px 28px rgba(0,0,0,.35)", border: "1px solid rgba(255,255,255,.08)"
  };
  return (
    <div style={{ position: "absolute", left: 12, top: 100, display: "grid", gap: 10, zIndex: 1000 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ ...btn, background: "#e11d48" }}>🔥</div>
        <div style={{ color: "#fff", fontWeight: 600 }}>Orman Yangın Analiz</div>
      </div>
    </div>
  );
}
function LegendDark() {
  const items = [
    { k: "Düşük şiddet | 0.1–0.27", c: "#22c55e" },
    { k: "Orta şiddet | 0.27–0.44", c: "#f59e0b" },
    { k: "Orta yüksek | 0.44–0.66", c: "#ef4444" },
    { k: "Çok yüksek şiddet | > 0.66", c: "#b91c1c" },
  ];
  return (
    <div style={{ position: "absolute", left: 16, bottom: 16, zIndex: 1000, background: "rgba(30,32,38,.78)", color: "#e5e7eb", borderRadius: 12, padding: 12, boxShadow: "0 10px 34px rgba(0,0,0,.45)", border: "1px solid rgba(255,255,255,.08)", backdropFilter: "blur(10px)" }}>
      {items.map(it => (
        <div key={it.k} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
          <span style={{ width: 12, height: 12, background: it.c, borderRadius: 2 }} />
          <span style={{ fontSize: 12 }}>{it.k}</span>
        </div>
      ))}
    </div>
  );
}

/** === Ağaçlandırma Önceliği Legend’i (priorityMode açıkken görünür) === */
function LegendPriority() {
  const items = [
    { k: "Çok yüksek öncelik (≥8)", c: "#4B0082" },
    { k: "Yüksek öncelik (6–7)", c: "#FF0000" },
    { k: "Orta öncelik (4–5)", c: "#FFA500" },
    { k: "Düşük öncelik (<4)", c: "#FFFF00" },
  ];
  return (
    <div style={{
      position: "absolute", left: 16, bottom: 130, zIndex: 1000,
      background: "rgba(30,32,38,.78)", color: "#e5e7eb",
      borderRadius: 12, padding: 12, boxShadow: "0 10px 34px rgba(0,0,0,.45)",
      border: "1px solid rgba(255,255,255,.08)", backdropFilter: "blur(10px)"
    }}>
      {items.map(it => (
        <div key={it.k} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
          <span style={{ width: 12, height: 12, background: it.c, borderRadius: 2 }} />
          <span style={{ fontSize: 12 }}>{it.k}</span>
        </div>
      ))}
    </div>
  );
}

const GLASS = { background: "rgba(30,32,38,.72)", color: "#e5e7eb", borderRadius: 16, padding: 14, marginBottom: 12, boxShadow: "0 12px 40px rgba(0,0,0,.45)", border: "1px solid rgba(255,255,255,.08)", backdropFilter: "blur(10px)" };
const BTN = { padding: "8px 10px", borderRadius: 10, background: "#334155", color: "#fff", border: "1px solid rgba(255,255,255,.12)" };
const BTN_ACCENT = on => ({ padding: "8px 10px", borderRadius: 10, background: on ? "#4f46e5" : "#3a3f4a", color: "#fff", border: "1px solid rgba(255,255,255,.12)" });

function SidePanel({
  clickPoint, onUseLocation, onClearPoint,
  onRouteFire, onRouteAssembly, routeLoading,
  useAssembly, setUseAssembly, showAssembly, setShowAssembly, refreshAssembly,
  selectedBurn, priorityMode, setPriorityMode
}) {
  return (
    <div style={{ position: "absolute", top: 70, right: 16, width: 340, zIndex: 1100 }}>
      <div style={GLASS}>
        <div style={{ fontWeight: 700, marginBottom: 8, color: "#fff" }}>Kontroller</div>
        <div style={{ fontSize: 12, marginBottom: 8, opacity: .85 }}>
          Seçili nokta {clickPoint ? `${clickPoint.lat.toFixed(5)}, ${clickPoint.lon.toFixed(5)}` : "—"}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button onClick={onUseLocation} style={BTN}>Konumumu Kullan</button>
          <button onClick={onClearPoint} style={{ ...BTN, background: "#3a3f4a" }}>Temizle</button>
        </div>
      </div>

      <div style={GLASS}>
        <div style={{ fontWeight: 700, marginBottom: 8, color: "#fff" }}>Rota</div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={onRouteFire} disabled={!clickPoint || routeLoading} style={BTN}>Yangın rotası</button>
          <button onClick={onRouteAssembly} disabled={!clickPoint || routeLoading} style={BTN}>Toplanma rotası</button>
        </div>
      </div>

      <div style={GLASS}>
        <div style={{ fontWeight: 700, marginBottom: 8, color: "#fff" }}>Toplanma alanları</div>
        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Yakınlığı hesapla</span>
            <button onClick={() => setUseAssembly(v => !v)} style={BTN_ACCENT(useAssembly)}>{useAssembly ? "Açık" : "Kapalı"}</button>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Katmanı göster</span>
            <button onClick={() => setShowAssembly(v => !v)} style={BTN_ACCENT(showAssembly)}>{showAssembly ? "Açık" : "Kapalı"}</button>
          </div>
          {useAssembly && <button onClick={refreshAssembly} style={{ ...BTN, background: "#4f46e5" }}>Görünür alanı yenile</button>}
        </div>
      </div>

      <div style={GLASS}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 700, color: "#fff" }}>Ağaçlandırma önceliği</div>
          <button onClick={() => setPriorityMode(v => !v)} style={BTN_ACCENT(priorityMode)}>{priorityMode ? "Açık" : "Kapalı"}</button>
        </div>
        {/* Liste kaldırıldı */}
      </div>

      <div style={GLASS}>
        <div style={{ fontWeight: 700, marginBottom: 8, color: "#fff" }}>Seçilen alan</div>
        {selectedBurn ? (
          <div style={{ fontSize: 13 }}>
            <div><b>Ad:</b> {selectedBurn.name || "—"}</div>
            <div><b>Şiddet:</b> {selectedBurn.severity || "—"}</div>
            <div><b>Alan:</b> {selectedBurn.areaHa != null ? `${Number(selectedBurn.areaHa).toLocaleString()} ha` : "—"}</div>
          </div>
        ) : <div style={{ fontSize: 12, opacity: .8 }}>Haritada bir yanık poligonuna tıkla.</div>}
      </div>
    </div>
  );
}

/** ========= Ana Bileşen ========= */
export default function App() {
  const [burnGeo, setBurnGeo] = useState(null);

  // Toplanma: hesaplama ve çizimi ayır
  const [useAssembly, setUseAssembly] = useState(false);     // yakınlık puanı
  const [showAssembly, setShowAssembly] = useState(false);   // haritada çizim
  const [assemblyGeo, setAssemblyGeo] = useState(null);

  const [clickPoint, setClickPoint] = useState(null);
  const [routeFire, setRouteFire] = useState(null);
  const [routeAssembly, setRouteAssembly] = useState(null);
  const [routeLoading, setRouteLoading] = useState(false);

  const [selectedBurn, setSelectedBurn] = useState(null);

  const [priorityMode, setPriorityMode] = useState(false);
  const scoreMapRef = useRef(new WeakMap());

  const mapRef = useRef(null);
  const lastBboxRef = useRef(null);
  const [currentBbox, setCurrentBbox] = useState(null);

  // Yanık alanları yükle
  useEffect(() => {
    (async () => {
      try {
        const u = new URL(DEFAULTS.burnAreasUrl, window.location.origin);
        u.searchParams.set("mode", "polys");
        const res = await fetch(u);
        setBurnGeo(await res.json());
      } catch (e) { console.error(e); }
    })();
  }, []);

  // GPS
  const useLocation = useCallback(() => {
    if (!("geolocation" in navigator)) return alert("Tarayıcı konum servisini desteklemiyor.");
    navigator.geolocation.getCurrentPosition(
      (pos) => setClickPoint({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => alert("Konum alınamadı. Lütfen izin verin."),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  }, []);
  const clearPoint = useCallback(() => { setClickPoint(null); setRouteFire(null); setRouteAssembly(null); }, []);

  // Rotalar
  const requestRoute = useCallback(async (kind) => {
    if (!clickPoint) return;
    try {
      setRouteLoading(true);
      const base = kind === "fire" ? DEFAULTS.routeToFireUrl : DEFAULTS.routeToAssemblyUrl;
      const u = new URL(base, window.location.origin);
      u.searchParams.set("lat", String(clickPoint.lat));
      u.searchParams.set("lon", String(clickPoint.lon));
      const res = await fetch(u);
      const data = await res.json();
      if (kind === "fire") setRouteFire(data); else setRouteAssembly(data);
    } catch (e) {
      console.error(e);
      if (kind === "fire") setRouteFire(null); else setRouteAssembly(null);
    } finally { setRouteLoading(false); }
  }, [clickPoint]);

  // Assembly fetch (bbox)
  const fetchAssemblyByBbox = useCallback(async (bbox) => {
    if (!useAssembly || !bbox) return;
    const key = bbox.join(",");
    if (lastBboxRef.current === key) return;
    lastBboxRef.current = key;
    try {
      const u = new URL(DEFAULTS.assemblyAreasUrl, window.location.origin);
      u.searchParams.set("bbox", key);
      const res = await fetch(u);
      setAssemblyGeo(await res.json());
    } catch (e) { console.error(e); setAssemblyGeo(null); }
  }, [useAssembly]);

  // Öncelik skoru hesap (renkler için skorları WeakMap'e yaz)
  useEffect(() => {
    scoreMapRef.current = new WeakMap();
    if (!burnGeo?.features?.length) return;

    const asmCenters = (assemblyGeo?.features || []).map(f => centroidOf(f)).filter(Boolean);

    for (const f of burnGeo.features) {
      const p = f.properties || {};
      const sev = p.severity_label || p.severity || "Düşük";
      let score = severityWeight(sev);
      const center = centroidOf(f);

      if (center && asmCenters.length) {
        let minKm = Infinity;
        for (const c of asmCenters) {
          const d = haversineKm({ lat: center.lat, lon: center.lon }, { lat: c.lat, lon: c.lon });
          if (d < minKm) minKm = d;
        }
        const nearestKm = isFinite(minKm) ? minKm : null;
        if (nearestKm != null) {
          if (nearestKm < 0.5) score += 10;
          else if (nearestKm < 1) score += 6;
          else if (nearestKm < 2.5) score += 3;
        }
      }

      scoreMapRef.current.set(f, score);
    }
  }, [burnGeo, assemblyGeo, priorityMode]);

  // Stil & popup
  const burnStyle = (feature) => {
    if (!priorityMode) {
      const label = feature?.properties?.severity_label || feature?.properties?.severity;
      const color = label && severityColors[label] ? severityColors[label] : "#f59e0b";
      return { color, weight: 1, fillColor: color, fillOpacity: 0.55 };
    }
    const score = scoreMapRef.current.get(feature) ?? 1;
    const fill = colorForPriority(score);
    return { color: fill, weight: 1, fillColor: fill, fillOpacity: 0.65 };
  };

  const onEachBurnFeature = (feature, layer) => {
    layer.on({
      mouseover: (e) => e.target.setStyle({ weight: 2, fillOpacity: 0.75 }),
      mouseout: (e) => e.target.setStyle(burnStyle(feature)),
      click: () => {
        const p = feature?.properties || {};
        setSelectedBurn({ name: p.name || p.id || "Alan", severity: p.severity_label || p.severity || "—", areaHa: p.area_ha ?? p.area ?? null });
      },
    });

    const p = feature?.properties || {};
    const sev = p.severity_label || p.severity || "—";
    const areaHa = p.area_ha ?? p.area ?? null;
    const score = scoreMapRef.current.get(feature);
    const showScore = priorityMode && score != null;

    const html = `
      <div style="min-width:200px">
        <div style="font-weight:600;margin-bottom:4px">${p.name || p.id || "Alan"}</div>
        <div><b>Şiddet:</b> ${sev}</div>
        ${areaHa ? `<div><b>Alan:</b> ${Number(areaHa).toLocaleString()} ha</div>` : ""}
        ${showScore ? `<div><b>Öncelik skoru:</b> ${score}</div>` : ""}
      </div>`;
    layer.bindPopup(html);
  };

  // Rota render
  const RouteLayer = ({ fc, color }) => {
    if (!fc?.features) return null;
    const line = fc.features.find(f => f.properties?.role === "line");
    const origin = fc.features.find(f => f.properties?.role === "origin");
    const dest = fc.features.find(f => f.properties?.role === "destination");
    return (
      <>
        {origin?.geometry?.coordinates && <Marker position={[origin.geometry.coordinates[1], origin.geometry.coordinates[0]]}><Popup>Başlangıç</Popup></Marker>}
        {dest?.geometry?.coordinates && <Marker position={[dest.geometry.coordinates[1], dest.geometry.coordinates[0]]}><Popup>Hedef</Popup></Marker>}
        {line?.geometry?.coordinates && (
          <Polyline positions={line.geometry.coordinates.map(c => [c[1], c[0]])} pathOptions={{ color, weight: 4, opacity: .9 }}>
            <Popup>Mesafe: {line.properties?.distance_km ?? (line.properties?.distance_m ? (line.properties.distance_m / 1000).toFixed(3) : "?")} km</Popup>
          </Polyline>
        )}
      </>
    );
  };

  // Bbox değişince hatırlayalım
  const refreshAssembly = useCallback(() => {
    if (currentBbox) { lastBboxRef.current = null; fetchAssemblyByBbox(currentBbox); }
  }, [currentBbox, fetchAssemblyByBbox]);

  return (
    <div style={{ position: "relative", width: "100vw", height: "100vh", background: "#0b0d10" }}>
      {/* Overlay UI */}
      <BrandTopCenter clickPoint={clickPoint} />
      <LeftToolbar />
      <LegendDark />
      {priorityMode && <LegendPriority />}

      <SidePanel
        clickPoint={clickPoint}
        onUseLocation={useLocation}
        onClearPoint={clearPoint}
        onRouteFire={() => requestRoute("fire")}
        onRouteAssembly={() => requestRoute("assembly")}
        routeLoading={routeLoading}
        useAssembly={useAssembly} setUseAssembly={setUseAssembly}
        showAssembly={showAssembly} setShowAssembly={setShowAssembly}
        refreshAssembly={refreshAssembly}
        selectedBurn={selectedBurn}
        priorityMode={priorityMode} setPriorityMode={setPriorityMode}
      />

      {/* Harita: tam ekran */}
      <MapContainer
        center={DEFAULTS.center}
        zoom={DEFAULTS.zoom}
        preferCanvas={true}
        style={{ position: "absolute", inset: 0 }}
        whenCreated={(m) => { mapRef.current = m; }}
      >
        <TileLayer
          attribution='&copy; OpenStreetMap | © SIRIUS'
          url="https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png"
        />

        {/* Yanık alanlar */}
        {burnGeo && (
          <GeoJSON
            key={`${priorityMode}-${assemblyGeo?.features?.length || 0}-${burnGeo?.features?.length || 0}`}
            data={burnGeo}
            style={burnStyle}
            onEachFeature={onEachBurnFeature}
          />
        )}

        {/* Yakınlık için sadece fetch */}
        <UseBboxFetcher enabled={useAssembly} onBoundsChange={(bbox) => { setCurrentBbox(bbox); fetchAssemblyByBbox(bbox); }} />

        {/* İstersen çiz: performans için kapalı */}
        {showAssembly && assemblyGeo && (
          <GeoJSON data={assemblyGeo} style={{ color: "#16A34A", weight: 1.5, fillColor: "#86EFAC", fillOpacity: .35 }} />
        )}

        {/* Tıklama → nokta */}
        <ClickToSelect onPoint={setClickPoint} />
        {clickPoint && (
          <Marker position={[clickPoint.lat, clickPoint.lon]}>
            <Popup>Seçili nokta<br />{clickPoint.lat.toFixed(5)}, {clickPoint.lon.toFixed(5)}</Popup>
          </Marker>
        )}

        {/* Rotalar */}
        <RouteLayer fc={routeFire} color="#1E90FF" />
        <RouteLayer fc={routeAssembly} color="#10B981" />
      </MapContainer>
    </div>
  );
}
