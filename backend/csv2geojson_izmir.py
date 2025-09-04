# csv2geojson_izmir.py
import os, sys, math
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

CSV = r"\izmir_toplanma.csv"  # indirdiğin dosya
OUT = r"\izmir_toplanma_alanlari.geojson"

# 1) CSV'yi sağlam şekilde oku (çeşitli encoding ve ayraç dene)
def robust_read_csv(path):
    encodings = ["utf-8", "utf-8-sig", "cp1254", "latin1", "iso-8859-9"]
    seps = [None, ";", ",", "\t", "|"]   # None -> Sniffer (engine=python)
    last_err = None
    for enc in encodings:
        for sep in seps:
            try:
                df = pd.read_csv(
                    path,
                    encoding=enc,
                    sep=sep,
                    engine="python",       # daha toleranslı
                    on_bad_lines="skip",   # sorunlu satırları atla
                )
                if df.shape[1] >= 2:
                    print(f"[OK] encoding={enc} sep={repr(sep)} -> {df.shape}")
                    return df
            except Exception as e:
                last_err = e
                continue
    raise last_err

# 2) Enlem/Boylam sütunlarını tahmin et
def find_lat_lon_cols(df):
    cols = {c.lower().strip(): c for c in df.columns}
    candidates = [
        ("enlem","boylam"),
        ("latitude","longitude"),
        ("lat","lon"),
        ("y","x"),                  # bazen böyle geliyor
        ("geom_y","geom_x"),        # olası türevler
    ]
    for lat_key, lon_key in candidates:
        if lat_key in cols and lon_key in cols:
            return cols[lat_key], cols[lon_key]
    # Son çare: sayısal 2 kolon bul ve isimlerine göre tahmin et
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if len(numeric_cols) >= 2:
        # isimlerden tahmin
        lon_guess = None
        lat_guess = None
        for c in df.columns:
            cl = c.lower()
            if lon_guess is None and any(k in cl for k in ["lon","long","boylam","x"]):
                lon_guess = c
            if lat_guess is None and any(k in cl for k in ["lat","enlem","y"]):
                lat_guess = c
        if lon_guess and lat_guess:
            return lat_guess, lon_guess
    raise SystemExit(f"Koordinat sütunları bulunamadı. Sütunlar: {list(df.columns)}")

# 3) Ondalık ve tip dönüşümleri (virgül/dot)
def to_float_series(s):
    # stringe çevir, boşlukları kırp
    s = s.astype(str).str.strip()
    # binlik ayırıcı nokta/virgül temizle
    s = s.str.replace("\xa0","", regex=False).str.replace(" ","", regex=False)
    # "41,12345" -> "41.12345"
    s = s.str.replace(",", ".", regex=False)
    # sayıya çevir
    s = pd.to_numeric(s, errors="coerce")
    return s

def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df = robust_read_csv(CSV)

    lat_col, lon_col = find_lat_lon_cols(df)
    print(f"[INFO] lat={lat_col} | lon={lon_col}")

    # sayıya çevir
    lat = to_float_series(df[lat_col])
    lon = to_float_series(df[lon_col])

    # makul koordinat filtresi (İzmir civarı enlem ~38–39.5, boylam ~26–28.5)
    ok = (
        lat.between(35, 42, inclusive="both") &
        lon.between(24, 32, inclusive="both")
    )
    bad = (~ok).sum()
    if bad:
        print(f"[WARN] {bad} satır makul koordinat aralığı dışında -> atlanacak")
    df = df[ok].copy()
    lat = lat[ok]; lon = lon[ok]

    # GeoDataFrame
    gdf = gpd.GeoDataFrame(
        df.reset_index(drop=True),
        geometry=[Point(xy) for xy in zip(lon, lat)],
        crs="EPSG:4326"
    )

    # boş geometri kontrolü
    gdf = gdf[gdf.geometry.notna()]
    if gdf.empty:
        raise SystemExit("Hiç geçerli nokta kalmadı. CSV sütun adlarını ve koordinatları kontrol et.")

    gdf.to_file(OUT, driver="GeoJSON")
    print("Yazıldı:", OUT)
    print("Kayıt sayısı:", len(gdf))
    print("Kolonlar:", list(gdf.columns))

if __name__ == "__main__":
    main()
