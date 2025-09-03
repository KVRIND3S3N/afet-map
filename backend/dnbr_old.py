import argparse, os, sys
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.features import shapes
import geopandas as gpd
from shapely.geometry import shape as shp_shape

def read_band(path):
    src = rasterio.open(path)
    arr = src.read(1).astype("float32")
    return src, arr

def scale_sr(arr, scale, offset=0.0):
    return arr * scale + offset

def align_to(ref_src, src, arr, resampling=Resampling.bilinear):
    dst_arr = np.empty((ref_src.height, ref_src.width), dtype="float32")
    reproject(source=arr, destination=dst_arr,
              src_transform=src.transform, src_crs=src.crs,
              dst_transform=ref_src.transform, dst_crs=ref_src.crs,
              resampling=resampling)
    return dst_arr

def nbr(nir, swir2, eps=1e-6):
    return (nir - swir2) / (nir + swir2 + eps)

def reclass_dnbr(dnbr_arr):
    classes = np.zeros_like(dnbr_arr, dtype="uint8")
    classes[(dnbr_arr >= 0.10) & (dnbr_arr < 0.27)] = 1
    classes[(dnbr_arr >= 0.27) & (dnbr_arr < 0.44)] = 2
    classes[dnbr_arr >= 0.44] = 3
    return classes

def write_raster(path, ref_src, arr, dtype="float32", nodata=None):
    meta = ref_src.meta.copy()
    meta.update(count=1, dtype=dtype, nodata=nodata)
    with rasterio.open(path, "w", **meta) as dst:
        dst.write(arr.astype(dtype), 1)

def polygonize(classes_arr, ref_src):
    mask = classes_arr > 0
    results = []
    for geom, val in shapes(classes_arr, mask=mask, transform=ref_src.transform):
        if val == 0: continue
        poly = shp_shape(geom)
        results.append({"geometry": poly, "class": int(val)})
    return gpd.GeoDataFrame(results, geometry="geometry", crs=ref_src.crs)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nir-before", required=True)
    parser.add_argument("--swir2-before", required=True)
    parser.add_argument("--nir-after", required=True)
    parser.add_argument("--swir2-after", required=True)
    parser.add_argument("--sensor", choices=["landsat", "sentinel", "raw"], default="raw")
    parser.add_argument("--out-dir", default="outputs")
    parser.add_argument("--vectorize", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    nir_b_src, nir_b = read_band(args.nir_before)
    swir_b_src, swir_b = read_band(args.swir2_before)
    nir_a_src, nir_a = read_band(args.nir_after)
    swir_a_src, swir_a = read_band(args.swir2_after)

    scale, offset = (1,0)
    if args.sensor == "landsat": scale, offset = (0.0000275,-0.2)
    if args.sensor == "sentinel": scale, offset = (0.0001,0)
    nir_b, swir_b, nir_a, swir_a = [scale_sr(x,scale,offset) for x in (nir_b,swir_b,nir_a,swir_a)]

    ref = nir_b_src
    swir_b = align_to(ref, swir_b_src, swir_b)
    nir_a  = align_to(ref, nir_a_src,  nir_a)
    swir_a = align_to(ref, swir_a_src, swir_a)

    nbr_before, nbr_after = nbr(nir_b, swir_b), nbr(nir_a, swir_a)
    dnbr_arr = nbr_before - nbr_after
    classes = reclass_dnbr(dnbr_arr)

    write_raster(os.path.join(args.out_dir,"dNBR.tif"), ref, dnbr_arr)
    write_raster(os.path.join(args.out_dir,"dNBR_classes.tif"), ref, classes, dtype="uint8", nodata=0)

    if args.vectorize:
        gdf = polygonize(classes, ref)
        gdf.to_file(os.path.join(args.out_dir,"burn_zones.geojson"), driver="GeoJSON")

    print("✓ dNBR analizi tamamlandı.")

if __name__ == "__main__":
    sys.exit(main())
