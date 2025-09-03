import os, getpass
import geopandas as gpd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from geoalchemy2 import Geometry
from sqlalchemy import text

# 🔹 DOSYA YOLUNU KENDİNE GÖRE KONTROL ET
SRC = r"C:\Users\furka\OneDrive\Masaüstü\afet\data\izmir_toplanma_alanlari.geojson"


# Shapefile Türkçe karakterli olabilir → Fiona motorunu kullan
os.environ["GEOPANDAS_IO_ENGINE"] = "fiona"

print("[INFO] Okunuyor:", SRC)
gdf = gpd.read_file(SRC)
print("[OK] Kayıt:", len(gdf), "| CRS:", gdf.crs)

# Geometri sütun adı 'geometry' değilse düzelt
if gdf.geometry.name != "geometry":
    gdf = gdf.set_geometry(gdf.geometry.name)

# CRS yoksa 4326 ata; varsa 4326'ya çevir
if gdf.crs is None:
    gdf = gdf.set_crs(4326)
elif gdf.crs.to_epsg() != 4326:
    gdf = gdf.to_crs(4326)

# Basit geometri onarımı
try:
    gdf["geometry"] = gdf.buffer(0)
except Exception:
    pass

# 🔹 DB bağlantısı (şifre güvenli sorulsun)
pw = getpass.getpass("Postgres parolan: ")
url = URL.create(
    "postgresql+psycopg2",
    username="postgres",
    password=pw,
    host="localhost",
    port=5432,
    database="afet",
)
engine = create_engine(url)

# 🔹 PostGIS'e yaz
gdf.to_postgis(
    "assembly_areas",
    engine,
    if_exists="replace",
    index=False,
    dtype={"geometry": Geometry("MULTIPOLYGON", srid=4326)}
)

# Spatial index
with engine.begin() as conn:
    conn.execute(text("""CREATE INDEX IF NOT EXISTS assembly_areas_gix
                         ON assembly_areas USING GIST (geometry);"""))


print("✅ assembly_areas yüklendi.")
