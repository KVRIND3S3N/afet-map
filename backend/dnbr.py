import os, sys, glob
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
import matplotlib.pyplot as plt

# ----------------- yardımcılar -----------------
def find_band(folder, key):
    """folder içinde adı key (Band5/Band7) içeren ilk TIF dosyasını döndür."""
    cand = glob.glob(os.path.join(folder, f"*{key}*.TIF")) + glob.glob(os.path.join(folder, f"*{key}*.tif"))
    if not cand:
        raise FileNotFoundError(f"{folder} içinde '{key}' içeren TIF bulunamadı.")
    return cand[0]

def read_and_align(src_path, ref_profile=None, ref_transform=None, ref_shape=None):
    """Rastırı float32 olarak oku; gerekirse referans grid’e reprojeksiyonla hizala."""
    with rasterio.open(src_path) as src:
        arr = src.read(1).astype("float32")
        # nodata -> NaN
        nod = src.nodatavals[0]
        if nod is not None:
            arr = np.where(arr == nod, np.nan, arr)

        if ref_profile is None:  # referans grid bu raster olsun
            return arr, src.profile, src.transform, src.crs

        out = np.full(ref_shape, np.nan, dtype="float32")
        reproject(
            source=arr,
            destination=out,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=ref_transform,
            dst_crs=ref_profile["crs"],
            resampling=Resampling.bilinear,
            num_threads=2
        )
        return out, ref_profile, ref_transform, ref_profile["crs"]

def safe_div(a, b):
    """(a/b) güvenli bölme."""
    denom = (a + b)
    out = (a - b) / np.where(np.abs(denom) < 1e-6, np.nan, (a + b))
    return out

def classify_dnbr(dnbr):
    """
    USGS (Key & Benson) eşikleri ile 5 sınıf:
      0: Unburned/unchanged        (dnbr < 0.10)
      1: Low severity               (0.10–0.27)
      2: Moderate-low               (0.27–0.44)
      3: Moderate-high              (0.44–0.66)
      4: High severity              (>= 0.66)
    """
    classes = np.full(dnbr.shape, 255, dtype="uint8")  # 255 = nodata
    mask = ~np.isnan(dnbr)

    bins = [0.10, 0.27, 0.44, 0.66]
    # <0.10
    m0 = mask & (dnbr < bins[0])
    classes[m0] = 0
    # 0.10–0.27
    m1 = mask & (dnbr >= bins[0]) & (dnbr < bins[1])
    classes[m1] = 1
    # 0.27–0.44
    m2 = mask & (dnbr >= bins[1]) & (dnbr < bins[2])
    classes[m2] = 2
    # 0.44–0.66
    m3 = mask & (dnbr >= bins[2]) & (dnbr < bins[3])
    classes[m3] = 3
    # >=0.66
    m4 = mask & (dnbr >= bins[3])
    classes[m4] = 4

    return classes

def summarize(classes, pix_area_m2):
    valid = classes != 255
    out = {}
    for k in [0,1,2,3,4]:
        cnt = int(np.sum(classes == k))
        ha  = cnt * pix_area_m2 / 10000.0
        out[k] = (cnt, ha)
    total_pix = int(np.sum(valid))
    total_ha  = total_pix * pix_area_m2 / 10000.0
    return out, total_pix, total_ha

# ----------------- ana akış -----------------
def main():
    root = os.getcwd()
    landsat_dir = os.path.join(root, "landsat")
    before_dir  = os.path.join(landsat_dir, "oncesi")
    after_dir   = os.path.join(landsat_dir, "sonrasi")
    out_dir     = os.path.join(root, "outputs")
    os.makedirs(out_dir, exist_ok=True)

    # Dosyaları bul
    b5_before = find_band(before_dir, "Band5")
    b7_before = find_band(before_dir, "Band7")
    b5_after  = find_band(after_dir,  "Band5")
    b7_after  = find_band(after_dir,  "Band7")

    print("Öncesi (B5):", os.path.basename(b5_before))
    print("Öncesi (B7):", os.path.basename(b7_before))
    print("Sonrası (B5):", os.path.basename(b5_after))
    print("Sonrası (B7):", os.path.basename(b7_after))

    # Referansı 'öncesi-B5' kabul et
    with rasterio.open(b5_before) as ref:
        ref_profile  = ref.profile
        ref_transform= ref.transform
        ref_crs      = ref.crs
        ref_shape    = ref.shape
        pix_area_m2  = abs(ref_transform[0] * ref_transform[4]) * -1  # ~ 900 m2 (30m x 30m) ama transform yönüne göre işaretlenebilir
        if pix_area_m2 <= 0:
            pix_area_m2 = abs(ref_transform.a * ref_transform.e)

    nir_b, prof, transform, crs = read_and_align(b5_before)  # referans
    sw2_b, _, _, _              = read_and_align(b7_before, ref_profile, ref_transform, ref_shape)
    nir_a, _, _, _              = read_and_align(b5_after,  ref_profile, ref_transform, ref_shape)
    sw2_a, _, _, _              = read_and_align(b7_after,  ref_profile, ref_transform, ref_shape)

    # NBR = (NIR - SWIR2) / (NIR + SWIR2)
    nbr_before = safe_div(nir_b, sw2_b)
    nbr_after  = safe_div(nir_a, sw2_a)

    # dNBR = before - after
    dnbr = nbr_before - nbr_after

    # Sınıflandır
    classes = classify_dnbr(dnbr)

    # GeoTIFF olarak kaydet
    out_tif = os.path.join(out_dir, "dnbr_5class.tif")
    profile = ref_profile.copy()
    profile.update(count=1, dtype="uint8", nodata=255, compress="deflate")
    with rasterio.open(out_tif, "w", **profile) as dst:
        dst.write(classes, 1)
        # basit renk tablosu (0..4)
        # 0: gri, 1: sarı, 2: turuncu, 3: kırmızı, 4: koyu kırmızı
        from rasterio.enums import ColorInterp
        from rasterio.io import MemoryFile
        # colormap sadece bazı görüntüleyicilerde görünür; yazalım
        cmap = {
            0: (190,190,190,255),  # gri
            1: (255,215,0,255),    # sarı
            2: (255,140,0,255),    # turuncu
            3: (220,20,60,255),    # kırmızı
            4: (128,0,0,255),      # koyu kırmızı
            255: (0,0,0,0)
        }
        dst.write_colormap(1, cmap)

    # Hızlı PNG önizleme + lejand
    out_png = os.path.join(out_dir, "dnbr_5class_quicklook.png")
    color_lut = np.array([
        [190,190,190],   # 0
        [255,215,0],     # 1
        [255,140,0],     # 2
        [220,20,60],     # 3
        [128,0,0],       # 4
        [0,0,0]          # 255 -> şeffaf/siyah
    ], dtype=np.uint8)
    rgb = np.zeros((classes.shape[0], classes.shape[1], 3), dtype=np.uint8)
    for k in [0,1,2,3,4]:
        rgb[classes==k] = color_lut[k]
    plt.figure(figsize=(9,7))
    plt.imshow(rgb)
    plt.axis('off')
    import matplotlib.patches as mpatches
    handles = [
        mpatches.Patch(color=np.array(color_lut[4])/255.0, label="4 Yüksek"),
        mpatches.Patch(color=np.array(color_lut[3])/255.0, label="3 Orta-Yüksek"),
        mpatches.Patch(color=np.array(color_lut[2])/255.0, label="2 Orta-Düşük"),
        mpatches.Patch(color=np.array(color_lut[1])/255.0, label="1 Düşük"),
        mpatches.Patch(color=np.array(color_lut[0])/255.0, label="0 Etkilenmemiş"),
    ]
    plt.legend(handles=handles, loc="lower right", frameon=True)
    plt.title("dNBR 5 Sınıf (B5/B7, Landsat)")
    plt.tight_layout()
    plt.savefig(out_png, dpi=200)
    plt.close()

    # Alan özeti
    summary, total_pix, total_ha = summarize(classes, pix_area_m2)
    print("\nSınıf piksel sayısı ve alan (hektar):")
    labels = {
        0: "0 Etkilenmemiş",
        1: "1 Düşük",
        2: "2 Orta-Düşük",
        3: "3 Orta-Yüksek",
        4: "4 Yüksek"
    }
    for k in [0,1,2,3,4]:
        cnt, ha = summary[k]
        print(f"  {labels[k]:<16}: {cnt:>10,} px  |  {ha:,.1f} ha")
    print(f"\nToplam geçerli piksel: {total_pix:,}")
    print(f"TİF:  {out_tif}")
    print(f"PNG:  {out_png}")

if __name__ == "__main__":
    main()
