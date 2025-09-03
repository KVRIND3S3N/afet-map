import { useCallback, useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, GeoJSON, Marker, Popup, Polyline, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

/**
 * Özellikler:
 * - Header + Sol panel + Harita (~78vh)
 * - 📍 Konumumu Kullan (GPS)
 * - Toplanma alanları toggle (bbox tabanlı fetch)
 * - Yanık alanları + poligon tıklayınca solda bilgi
 * - Rota butonları (yangın/toplanma)
 * - 🟢 Ağaçlandırma Önceliği: severity + assembly yakınlığı (frontend-only)
 * - 🆕 Listede elemana tıklayınca haritaya zoom (flyTo)
 */

// --------- Sabitler
const DEFAULTS = {
  center: [38.5, 27.5],
  zoom: 8,
  burnAreasUrl: "/api/burn-areas",
  assemblyAreasUrl: "/api/assembly-areas",
  routeToFireUrl: "/api/route-to-fire",
  routeToAssemblyUrl: "/api/route-to-assembly",
};

// Yanık şiddeti → renk
const severityColors = {
  "Etkilenmemiş": "#D9D9D9",
  "Düşük": "#FFE08A",
  "Orta-Düşük": "#FFA552",
  "Orta-Yüksek": "#E0523E",
  "Yüksek": "#9E1C1C",
};

// Soldaki kartta görünecek örnek aralıklar
const panelSeverityLegend = [
  { label: "Yanmamış Alan", range: "", color: "#86EFAC" },
  { label: "Düşük Şiddet", range: "(0.1–0.27)", color: "#A3E635" },
  { label: "Orta Şiddet", range: "(0.27–0.44)", color: "#F59E0B" },
  { label: "Yüksek Şiddet", range: "(0.44–0.66)", color: "#EF4444" },
  { label: "Çok Yüksek Şiddet", range: "(>0.66)", color: "#B91C1C" },
];

// --------- Leaflet marker ikon fix
const DefaultIcon = new L.Icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  tooltipAnchor: [16, -28],
  shadowSize: [41, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

// --------- Priority helpers (frontend-only)
function haversineKm(a, b) {
  const R = 6371; // km
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const s1 = Math.sin(dLat / 2) ** 2;
  const s2 = Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s1 + s2));
}
// Çokgen/çok-çokgen için basit centroid
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
  if (label === "Yüksek") return 3;
  if (label === "Orta-Yüksek") return 2;
  return 1; // Düşük/Orta-Düşük/Etkilenmemiş
}
function colorForPriority(score) {
  // 1-2 düşük, 3-4 orta, 5-6 yüksek, 7+ çok yüksek
  if (score >= 7) return "#7f1d1d";
  if (score >= 5) return "#dc2626";
  if (score >= 3) return "#f97316";
  return "#fde047";
}

// --------- Harita içi yardımcılar
function UseBboxFetcher({ enabled, onBoundsChange, debounceMs = 400 }) {
  const map = useMap();
  const tRef = useRef(null);
  useEffect(() => {
    if (!enabled) return;
    const fire = () => {
      const b = map.getBounds();
      const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
      onBoundsChange?.(bbox);
    };
    fire(); // ilk yükleme
    const onMoveEnd = () => {
      if (tRef.current) clearTimeout(tRef.current);
      tRef.current = setTimeout(fire, debounceMs);
    };
    map.on("moveend", onMoveEnd);
    return () => {
      map.off("moveend", onMoveEnd);
      if (tRef.current) clearTimeout(tRef.current);
    };
  }, [enabled, onBoundsChange, debounceMs, map]);
  return null;
}

function ClickToSelect({ onPoint }) {
  useMapEvents({
    click(e) {
      onPoint?.({ lat: e.latlng.lat, lon: e.latlng.lng });
    },
  });
  return null;
}

// --------- Üst Header
function Header() {
  return (
    <div style={{ height: 56, background: "#111827", color: "#fff", display: "flex", alignItems: "center", padding: "0 16px", justifyContent: "space-between" }}>
      <div style={{ fontWeight: 700 }}>🔥 Afet Analiz Paneli</div>
      <nav style={{ display: "flex", gap: 16, opacity: 0.9 }}>
        <span>Ana Sayfa</span>
        <span>Harita</span>
        <span>Sürdürülebilir Şehir</span>
      </nav>
    </div>
  );
}

// --------- Sol Panel
function SidePanel({
  clickPoint,
  onUseLocation,
  onClearPoint,
  onRouteFire,
  onRouteAssembly,
  routeLoading,
  assemblyEnabled,
  setAssemblyEnabled,
  onRefreshAssembly,
  selectedBurn,
  priorityMode,
  setPriorityMode,
  priorityTop,
  onFocusArea, // 🆕 listeden tıklayınca haritayı uçur
}) {
  return (
    <div style={{ width: 320, padding: 16 }}>
      {/* Kontroller */}
      <div style={{ background: "#fff", borderRadius: 16, boxShadow: "0 6px 20px rgba(0,0,0,.1)", padding: 14, marginBottom: 12 }}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Kontroller</div>

        <div style={{ fontSize: 13, marginBottom: 8, color: "#374151" }}>
          Seçili nokta: {clickPoint ? `${clickPoint.lat.toFixed(5)}, ${clickPoint.lon.toFixed(5)}` : "—"}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button onClick={onUseLocation} style={{ padding: "8px 10px", borderRadius: 10, background: "#111", color: "#fff" }}>
            📍 Konumumu Kullan
          </button>
          <button onClick={onClearPoint} style={{ padding: "8px 10px", borderRadius: 10, background: "#e5e7eb" }}>
            Temizle
          </button>
        </div>

        <div style={{ height: 1, background: "#e5e7eb", margin: "12px 0" }} />

        <div style={{ fontWeight: 600, marginBottom: 6 }}>Rota</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={onRouteFire}
            disabled={!clickPoint || routeLoading}
            style={{ padding: "8px 10px", borderRadius: 10, background: !clickPoint || routeLoading ? "#9ca3af" : "#111", color: "#fff" }}
          >
            Yangın Rotası
          </button>
          <button
            onClick={onRouteAssembly}
            disabled={!clickPoint || routeLoading}
            style={{ padding: "8px 10px", borderRadius: 10, background: !clickPoint || routeLoading ? "#9ca3af" : "#111", color: "#fff" }}
          >
            Toplanma Rotası
          </button>
        </div>

        <div style={{ height: 1, background: "#e5e7eb", margin: "12px 0" }} />

        {/* Toplanma alanları toggle */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <div style={{ fontWeight: 700 }}>Toplanma Alanları</div>
          <button onClick={() => setAssemblyEnabled(v => !v)} style={{ padding: "6px 10px", borderRadius: 8, background: assemblyEnabled ? "#16a34a" : "#e5e7eb", color: assemblyEnabled ? "#fff" : "#111" }}>
            {assemblyEnabled ? "Açık" : "Kapalı"}
          </button>
        </div>
        {assemblyEnabled && (
          <button onClick={onRefreshAssembly} style={{ marginTop: 8, padding: "6px 10px", borderRadius: 8, background: "#2563eb", color: "#fff", width: "100%" }}>
            Görünür Alanı Yenile
          </button>
        )}
      </div>

      {/* Ağaçlandırma Önceliği */}
      <div style={{ background: "#fff", borderRadius: 16, boxShadow: "0 6px 20px rgba(0,0,0,.1)", padding: 14, marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontWeight: 700 }}>Ağaçlandırma Önceliği</div>
          <button
            onClick={() => setPriorityMode(v => !v)}
            style={{ padding: "6px 10px", borderRadius: 8, background: priorityMode ? "#1f2937" : "#e5e7eb", color: priorityMode ? "#fff" : "#111" }}
          >
            {priorityMode ? "Açık" : "Kapalı"}
          </button>
        </div>

        {priorityTop.length ? (
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 6 }}>İlk 5 saha (skora göre):</div>
            <div style={{ display: "grid", gap: 6 }}>
              {priorityTop.map((r, i) => (
                <button
                  key={i}
                  onClick={() => onFocusArea?.(r)}
                  style={{
                    textAlign: "left",
                    cursor: "pointer",
                    fontSize: 13,
                    background: "#f9fafb",
                    border: "1px solid #e5e7eb",
                    borderRadius: 8,
                    padding: 8,
                  }}
                >
                  <div style={{ fontWeight: 700 }}>{i + 1}. {r.name}</div>
                  <div>Skor: {r.score}{r.nearestKm != null && <> • Yakınlık: {r.nearestKm.toFixed(1)} km</>}</div>
                  <div>Alan: {r.areaHa != null ? `${Number(r.areaHa).toLocaleString()} ha` : "—"}</div>
                  <div>Şiddet: {r.severity}</div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 13, color: "#6b7280", marginTop: 8 }}>Öncelik listesi henüz oluşmadı.</div>
        )}
      </div>

      {/* Seçilen Yanık Alanı Özeti */}
      <div style={{ background: "#fff", borderRadius: 16, boxShadow: "0 6px 20px rgba(0,0,0,.1)", padding: 14, marginBottom: 12 }}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Seçilen Alan</div>
        {selectedBurn ? (
          <div style={{ fontSize: 13, color: "#111" }}>
            <div style={{ marginBottom: 4 }}><b>Ad:</b> {selectedBurn.name || "—"}</div>
            <div style={{ marginBottom: 4 }}><b>Şiddet:</b> {selectedBurn.severity || "—"}</div>
            <div><b>Alan:</b> {selectedBurn.areaHa != null ? `${Number(selectedBurn.areaHa).toLocaleString()} ha` : "—"}</div>
          </div>
        ) : (
          <div style={{ fontSize: 13, color: "#6b7280" }}>Haritada bir yanık poligonuna tıkla.</div>
        )}
      </div>

      {/* Yangın Şiddeti Sınıfları Kartı */}
      <div style={{ background: "#fff", borderRadius: 16, boxShadow: "0 6px 20px rgba(0,0,0,.1)", padding: 14 }}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>🔥 Yangın Şiddeti Sınıfları</div>
        <div style={{ display: "grid", gap: 8 }}>
          {panelSeverityLegend.map((it) => (
            <div key={it.label} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
              <span style={{ width: 14, height: 14, borderRadius: 3, background: it.color, display: "inline-block" }} />
              <span>{it.label} {it.range && <span style={{ color: "#6b7280" }}>{it.range}</span>}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// --------- Ana Bileşen
export default function App() {
  const [burnGeo, setBurnGeo] = useState(null);
  const [assemblyGeo, setAssemblyGeo] = useState(null);
  const [assemblyEnabled, setAssemblyEnabled] = useState(false);

  const [clickPoint, setClickPoint] = useState(null);
  const [routeFire, setRouteFire] = useState(null);
  const [routeAssembly, setRouteAssembly] = useState(null);
  const [routeLoading, setRouteLoading] = useState(false);

  const [selectedBurn, setSelectedBurn] = useState(null); // {name, severity, areaHa}

  // --- Öncelik modu ---
  const [priorityMode, setPriorityMode] = useState(false);
  const [priorityTop, setPriorityTop] = useState([]); // ilk 5 saha
  const scoreMapRef = useRef(new WeakMap()); // feature -> score

  // 🆕 Harita referansı
  const mapRef = useRef(null);

  // Yanık alanları yükle (polys)
  useEffect(() => {
    (async () => {
      try {
        const u = new URL(DEFAULTS.burnAreasUrl, window.location.origin);
        u.searchParams.set("mode", "polys");
        const res = await fetch(u);
        const data = await res.json();
        setBurnGeo(data);
      } catch (e) { console.error(e); }
    })();
  }, []);

  // GPS ile konum al
  const useLocation = useCallback(() => {
    if (!("geolocation" in navigator)) {
      alert("Tarayıcı konum servisini desteklemiyor.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        setClickPoint({ lat: latitude, lon: longitude });
      },
      (err) => {
        console.error(err);
        alert("Konum alınamadı. Lütfen izin verdiğinizden emin olun.");
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  }, []);

  const clearPoint = useCallback(() => {
    setClickPoint(null);
    setRouteFire(null);
    setRouteAssembly(null);
  }, []);

  // Rota istekleri
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

  // Assembly fetch (bbox tabanlı)
  const lastBboxRef = useRef(null);
  const [currentBbox, setCurrentBbox] = useState(null);
  const fetchAssemblyByBbox = useCallback(async (bbox) => {
    if (!assemblyEnabled || !bbox) return;
    const key = bbox.join(",");
    if (lastBboxRef.current === key) return;
    lastBboxRef.current = key;
    try {
      const u = new URL(DEFAULTS.assemblyAreasUrl, window.location.origin);
      u.searchParams.set("geom", "polygons");
      u.searchParams.set("bbox", key); // minLon,minLat,maxLon,maxLat
      const res = await fetch(u);
      const data = await res.json();
      setAssemblyGeo(data);
    } catch (e) { console.error(e); setAssemblyGeo(null); }
  }, [assemblyEnabled]);

  // Öncelik skoru hesapla (burnGeo/assemblyGeo değiştikçe)
  useEffect(() => {
    scoreMapRef.current = new WeakMap();
    if (!burnGeo?.features?.length) { setPriorityTop([]); return; }

    const asmCenters = (assemblyGeo?.features || []).map(f => centroidOf(f)).filter(Boolean);

    const rows = burnGeo.features.map(f => {
      const p = f.properties || {};
      const sev = p.severity_label || p.severity || "Düşük";
      let score = severityWeight(sev);
      let nearestKm = null;

      const center = centroidOf(f);
      if (center && asmCenters.length) {
        let minKm = Infinity;
        for (const c of asmCenters) {
          const d = haversineKm({ lat: center.lat, lon: center.lon }, { lat: c.lat, lon: c.lon });
          if (d < minKm) minKm = d;
        }
        nearestKm = isFinite(minKm) ? minKm : null;
        if (nearestKm != null) {
          if (nearestKm < 2) score += 2;
          else if (nearestKm < 5) score += 1;
        }
      }

      scoreMapRef.current.set(f, score); // stil için sakla

      return {
        name: p.name || p.id || "Alan",
        areaHa: p.area_ha ?? p.area ?? null,
        severity: sev,
        score,
        nearestKm,
        center: center ? [center.lat, center.lon] : null, // 🆕 zoom için
        feature: f,
      };
    });

    rows.sort((a, b) => b.score - a.score);
    setPriorityTop(rows.slice(0, 5));
  }, [burnGeo, assemblyGeo]);

  // --------- Stil ve poligon etkileşimleri
  const burnStyle = (feature) => {
    if (!priorityMode) {
      const label = feature?.properties?.severity_label || feature?.properties?.severity;
      const color = label && severityColors[label] ? severityColors[label] : "#FF5722";
      return { color, weight: 1, fillColor: color, fillOpacity: 0.55 };
    }
    // priority mode: hesaplanmış skor ile boya
    const score = scoreMapRef.current.get(feature) ?? 1;
    const fill = colorForPriority(score);
    return { color: fill, weight: 1, fillColor: fill, fillOpacity: 0.65 };
  };

  const onEachBurnFeature = (feature, layer) => {
    layer.on({
      mouseover: (e) => { e.target.setStyle({ weight: 2, fillOpacity: 0.75 }); },
      mouseout: (e) => { e.target.setStyle(burnStyle(feature)); },
      click: () => {
        const p = feature?.properties || {};
        setSelectedBurn({
          name: p.name || p.id || "Alan",
          severity: p.severity_label || p.severity || "—",
          areaHa: p.area_ha ?? p.area ?? null,
        });
      },
    });
    const p = feature?.properties || {};
    const sev = p.severity_label || p.severity || "—";
    const areaHa = p.area_ha ?? p.area ?? null;
    const score = scoreMapRef.current.get(feature);
    const html = `
      <div style="min-width:200px">
        <div style="font-weight:600;margin-bottom:4px">${p.name || p.id || "Alan"}</div>
        <div><b>Şiddet:</b> ${sev}</div>
        ${areaHa ? `<div><b>Alan:</b> ${Number(areaHa).toLocaleString()} ha</div>` : ""}
        ${score != null ? `<div><b>Öncelik skoru:</b> ${score}</div>` : ""}
      </div>
    `;
    layer.bindPopup(html);
  };

  // --------- Rota render
  const RouteLayer = ({ fc, color }) => {
    if (!fc || !fc.features) return null;
    const line = fc.features.find((f) => f.properties?.role === "line");
    const origin = fc.features.find((f) => f.properties?.role === "origin");
    const dest = fc.features.find((f) => f.properties?.role === "destination");
    return (
      <>
        {origin?.geometry?.coordinates && (
          <Marker position={[origin.geometry.coordinates[1], origin.geometry.coordinates[0]]}><Popup>Başlangıç</Popup></Marker>
        )}
        {dest?.geometry?.coordinates && (
          <Marker position={[dest.geometry.coordinates[1], dest.geometry.coordinates[0]]}><Popup>Hedef</Popup></Marker>
        )}
        {line?.geometry?.coordinates && (
          <Polyline positions={line.geometry.coordinates.map((c) => [c[1], c[0]])} pathOptions={{ color, weight: 4, opacity: .9 }}>
            <Popup>
              Mesafe: {line.properties?.distance_km ?? (line.properties?.distance_m ? (line.properties.distance_m/1000).toFixed(3) : "?")} km
            </Popup>
          </Polyline>
        )}
      </>
    );
  };

  // 🆕 Listeden tıklanınca haritaya uçur
  const onFocusArea = useCallback((row) => {
    if (!row?.center || !mapRef.current) return;
    mapRef.current.flyTo(row.center, 13, { duration: 0.9 });
    // İPUCU: İstersen burada kısa süreli highlight/marker da ekleyebiliriz.
  }, []);

  // --------- Layout
  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "#f3f4f6" }}>
      <Header />

      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 0, padding: 12, alignItems: "start" }}>
        <SidePanel
          clickPoint={clickPoint}
          onUseLocation={useLocation}
          onClearPoint={clearPoint}
          onRouteFire={() => requestRoute("fire")}
          onRouteAssembly={() => requestRoute("assembly")}
          routeLoading={routeLoading}
          assemblyEnabled={assemblyEnabled}
          setAssemblyEnabled={setAssemblyEnabled}
          onRefreshAssembly={() => {
            if (currentBbox) {
              lastBboxRef.current = null; // zorla yenile
              fetchAssemblyByBbox(currentBbox);
            }
          }}
          selectedBurn={selectedBurn}
          priorityMode={priorityMode}
          setPriorityMode={setPriorityMode}
          priorityTop={priorityTop}
          onFocusArea={onFocusArea} // 🆕
        />

        <div style={{ background: "#fff", borderRadius: 16, boxShadow: "0 6px 20px rgba(0,0,0,.1)", padding: 8 }}>
          <div style={{ height: "78vh", position: "relative" }}>
            <MapContainer
              center={DEFAULTS.center}
              zoom={DEFAULTS.zoom}
              style={{ height: "100%", width: "100%" }}
              whenCreated={(map) => { mapRef.current = map; }} // 🆕 harita referansı
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              {/* Yanık alanlar */}
              {burnGeo && <GeoJSON data={burnGeo} style={burnStyle} onEachFeature={onEachBurnFeature} />}

              {/* Toplanma alanları */}
              {assemblyEnabled && (
                <>
                  <UseBboxFetcher
                    enabled={assemblyEnabled}
                    onBoundsChange={(bbox) => {
                      setCurrentBbox(bbox);
                      fetchAssemblyByBbox(bbox);
                    }}
                  />
                  {assemblyGeo && <GeoJSON data={assemblyGeo} style={{ color: "#16A34A", weight: 1.5, fillColor: "#86EFAC", fillOpacity: 0.35 }} />}
                </>
              )}

              {/* Harita tıklama → seçili nokta */}
              <ClickToSelect onPoint={setClickPoint} />

              {clickPoint && (
                <Marker position={[clickPoint.lat, clickPoint.lon]}>
                  <Popup>Seçili nokta<br/> {clickPoint.lat.toFixed(5)}, {clickPoint.lon.toFixed(5)}</Popup>
                </Marker>
              )}

              {/* Rotalar */}
              <RouteLayer fc={routeFire} color="#1E90FF" />
              <RouteLayer fc={routeAssembly} color="#10B981" />
            </MapContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
