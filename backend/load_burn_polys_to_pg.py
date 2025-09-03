from sqlalchemy import create_engine
from geoalchemy2 import Geometry
import geopandas as gpd

# 🔹 Veritabanı bağlantısı (kendi şifreni yaz)
DB_USER = "postgres"
DB_PASS = "2323"
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "afet"

engine = create_engine(f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

# 🔹 Yanık alan poligonlarını oku
gdf = gpd.read_file("outputs/burn_polys.gpkg")

# 🔹 Eğer CRS yoksa EPSG:4326 ata
if gdf.crs is None:
    gdf = gdf.set_crs(epsg=4326)

print("CRS:", gdf.crs)
print("Toplam poligon sayısı:", len(gdf))

# 🔹 PostGIS'e yaz
gdf.to_postgis("burn_polys", engine, if_exists="replace", index=False, dtype={"geometry": Geometry("POLYGON", srid=4326)})

print("✅ burn_polys tablosu PostGIS'e yüklendi.")
