import rasterio
from rasterio.features import shapes
import numpy as np
import geopandas as gpd
from shapely.geometry import shape

# GİRDİ/ÇIKTI
tif = r"C:\Users\furka\OneDrive\Masaüstü\afet\outputs\dnbr_5class.tif"
out_gpkg = r"C:\Users\furka\OneDrive\Masaüstü\afet\outputs\burn_polys.gpkg"  # tek dosya, sağlam format
layer = "burn_polys"

with rasterio.open(tif) as src:
    img = src.read(1)
    mask = (img >= 2)  # sınıf 2/3/4: etkilenen alanlar
    results = shapes(img, mask=mask, transform=src.transform)

geoms = []
vals = []
for geom, val in results:
    geoms.append(shape(geom))
    vals.append(int(val))

gdf = gpd.GeoDataFrame({"class": vals}, geometry=geoms, crs="EPSG:32635")  # dNBR’ımız UTM35’ti
gdf = gdf.explode(ignore_index=True)  # çokgenleri ayır
# sadeleştir (opsiyonel, dosya boyutunu küçültür):
gdf["geometry"] = gdf.geometry.buffer(0)

# WGS84'e çevir (web/DB için iyi pratik)
gdf = gdf.to_crs(4326)
gdf.to_file(out_gpkg, layer=layer, driver="GPKG")
print(f"Yazıldı: {out_gpkg} (layer={layer}), {len(gdf)} parça")
