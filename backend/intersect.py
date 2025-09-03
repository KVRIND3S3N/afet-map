# risk_by_distance.py
# dNBR 5-sınıf rasterdan yanık maskesi üretir, toplanma alanlarını
# YANIK ALANINA MESAFEYE göre risk bantlarına ayırır.
# Çıktılar: GeoJSON/CSV + 2 PNG harita

import os, warnings
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import unary_union, nearest_points
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

# ----------------- AYARLAR -----------------
BASE = os.path.dirname(__file__)
RASTER_PATH = os.path.join(BASE, "outputs", "dnbr_5class.tif")
TOP_PATH = os.path.join(BASE, "data", "izmir_toplanma_alanlari.geojson")
OUTDIR      = os.path.join(BASE, "outputs")
os.makedirs(OUTDIR, exist_ok=True)

# Hangi sınıflar "yanık" sayılacak?
BURN_CLASSES = {2, 3, 4}           # istersen {3,4} yap

# Mesafe bantları (metre) -> etiket
# sınırlar [min, max) olarak yorumlanır; sıralama önemli
DIST_BANDS = [
    (0,    250,   "Çok Yüksek"),
    (250,  500,   "Yüksek"),
    (500,  1000,  "Orta"),
    (1000, 5000,  "Düşük"),
    (5000, 1e12,  "Güvenli"),
]

# Harita için nokta limiti
MAX_PLOT = 20000

# --------------- YARDIMCI ------------------
def read_shp_robust(path):
    last = None
    for eng in ("pyogrio", "fiona"):
        for enc in (None, "cp1254", "latin1", "iso-8859-9"):
            try:
                kw = {"engine": eng}
                if enc: kw["encoding"] = enc
                return gpd.read_file(path, **kw)
            except Exception as e:
                last = e
    raise last

try:
    from shapely.validation import make_valid
except Exception:
    make_valid = None

def fix_geoms(gdf):
    if gdf is None or gdf.empty: return gdf
    g = gdf[gdf.geometry.notna()]
    g = g[~g.geometry.is_empty]
    if make_valid is not None:
        g["geometry"] = g["geometry"].apply(make_valid)
    else:
        g["geometry"] = g.buffer(0)
    return g[~g.geometry.is_empty]

def classify_distance(d):
    for lo, hi, label in DIST_BANDS:
        if lo <= d < hi:
            return label
    return "Bilinmiyor"

def plot_maps(bounds, pts, title_extra=""):
    # Tümü
    fig, ax = plt.subplots(figsize=(10, 8))
    colors = {
        "Çok Yüksek":"#ff0000",
        "Yüksek":"#ff7f0e",
        "Orta":"#f2c744",
        "Düşük":"#7cb342",
        "Güvenli":"#2ecc71"
    }
    for label, df in pts.groupby("risk_band"):
        df.plot(ax=ax, color=colors.get(label, "gray"), markersize=8, label=label)
    if bounds:
        l,b,r,t = bounds
        ax.plot([l,r,r,l,l],[b,b,t,t,b], color="crimson", lw=1)
    ax.set_title(f"Toplanma Alanları — Mesafeye Göre Risk {title_extra}")
    ax.set_axis_off(); ax.legend(loc="lower right", frameon=True, ncol=2)
    out = os.path.join(OUTDIR, "risk_distance_full.png")
    plt.tight_layout(); plt.savefig(out, dpi=200); plt.close()

    # Zoom
    if bounds:
        fig, ax = plt.subplots(figsize=(10, 8))
        for label, df in pts.groupby("risk_band"):
            df.plot(ax=ax, color=colors.get(label, "gray"), markersize=10, label=label)
        l,b,r,t = bounds
        pad = 2000
        ax.set_xlim(l-pad, r+pad); ax.set_ylim(b-pad, t+pad)
        ax.set_title("Yakın Görünüm — Raster BOUNDS çevresi")
        ax.set_axis_off(); ax.legend(loc="lower right", frameon=True, ncol=2)
        out2 = os.path.join(OUTDIR, "risk_distance_zoom.png")
        plt.tight_layout(); plt.savefig(out2, dpi=200); plt.close()
        return out, out2
    return out, None

# --------------- ANA -----------------------
def main():
    # 1) Rasteri aç ve yanık maskesini poligonlaştır
    with rasterio.open(RASTER_PATH) as src:
        arr = src.read(1).astype(float)
        crs = src.crs
        nodata = src.nodata
        bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
        trf = src.transform

    if nodata is not None:
        arr[arr == nodata] = np.nan

    # yanık maskesi
    burn_mask = np.isin(arr, list(BURN_CLASSES))
    if not burn_mask.any():
        print("UYARI: Yanık sınıfı piksel bulunamadı.")
    geoms = [shape(g) for g, v in shapes(arr, mask=burn_mask, transform=trf) if np.isfinite(v)]
    burn = gpd.GeoDataFrame(geometry=geoms, crs=crs)
    burn = fix_geoms(burn)
    if burn.empty:
        print("UYARI: Yanık poligonu üretilmedi (mask boş).")
        return
    burn_union = unary_union(burn.geometry)

    # 2) Toplanma alanlarını oku → centroid
    top = read_shp_robust(TOP_PATH)
    if top.crs != crs:
        top = top.to_crs(crs)
    top = fix_geoms(top)
    if top.empty:
        print("Toplanma alanı boş.")
        return
    pts = top.copy()
    pts["geometry"] = pts.geometry.centroid

    # 3) distance (metre) + risk bandı
    dists = pts.geometry.apply(lambda g: g.distance(nearest_points(g, burn_union)[1]))
    pts["dist_m"] = dists.astype(float)
    pts["risk_band"] = pts["dist_m"].apply(classify_distance)

    # 4) Çıktılar
    out_geo = os.path.join(OUTDIR, "toplanma_risk_by_distance.geojson")
    out_csv = os.path.join(OUTDIR, "toplanma_risk_by_distance.csv")
    pts.to_crs(4326).to_file(out_geo, driver="GeoJSON")
    pts.drop(columns="geometry").to_csv(out_csv, index=False, encoding="utf-8-sig")

    # Harita
    plot_pts = pts.copy()
    if len(plot_pts) > MAX_PLOT:
        plot_pts = plot_pts.sample(MAX_PLOT, random_state=42)
    full_png, zoom_png = plot_maps(bounds, plot_pts, title_extra=f"(sınıflar={sorted(BURN_CLASSES)})")

    # 5) Özet
    print("\nÖZET — Mesafeye göre risk dağılımı")
    for label in [b[2] for b in DIST_BANDS]:
        n = int((pts["risk_band"] == label).sum())
        print(f"  {label:10s}: {n:,}")
    print("\nYazılan dosyalar:")
    print(" ", out_geo)
    print(" ", out_csv)
    print(" ", full_png)
    if zoom_png: print(" ", zoom_png)

if __name__ == "__main__":
    main()
