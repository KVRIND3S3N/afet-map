# verify_dnbr.py — NBR before/after, dNBR (5 sınıf) doğrulama
import os, glob
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
import matplotlib.pyplot as plt

ROOT = os.getcwd()
OUT  = os.path.join(ROOT, "outputs", "verify")
os.makedirs(OUT, exist_ok=True)

def pick(pattern):
    # landsat/oncesi ve landsat/sonrasi altında ara
    c = glob.glob(os.path.join("landsat","oncesi",pattern)) + \
        glob.glob(os.path.join("landsat","sonrasi",pattern))
    if not c:
        raise FileNotFoundError(f"Bulunamadı: {pattern}")
    return c[0]

def read_and_align(path, ref_prof=None, ref_transform=None, ref_shape=None):
    with rasterio.open(path) as src:
        arr = src.read(1).astype("float32")
        nd = src.nodatavals[0]
        if nd is not None:
            arr = np.where(arr == nd, np.nan, arr)
        if ref_prof is None:
            return arr, src.profile, src.transform, src.crs, src.shape
        out = np.full(ref_shape, np.nan, dtype="float32")
        reproject(
            arr, out,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=ref_transform, dst_crs=ref_prof["crs"],
            resampling=Resampling.bilinear, num_threads=2
        )
        return out, ref_prof, ref_transform, ref_prof["crs"], ref_shape

def safe_div(a,b):
    d = (a+b)
    return (a-b) / np.where(np.abs(d)<1e-6, np.nan, d)

def classify_5(dnbr):
    """
    5 sınıf (USGS/Key & Benson):
      0: <0.10  (Etkilenmemiş)
      1: 0.10–0.27 (Düşük)
      2: 0.27–0.44 (Orta-Düşük)
      3: 0.44–0.66 (Orta-Yüksek)
      4: >=0.66   (Yüksek)
    """
    classes = np.full(dnbr.shape, 255, dtype="uint8")
    m = ~np.isnan(dnbr)
    bins = [0.10, 0.27, 0.44, 0.66]
    classes[m & (dnbr <  bins[0])] = 0
    classes[m & (dnbr >= bins[0]) & (dnbr < bins[1])] = 1
    classes[m & (dnbr >= bins[1]) & (dnbr < bins[2])] = 2
    classes[m & (dnbr >= bins[2]) & (dnbr < bins[3])] = 3
    classes[m & (dnbr >= bins[3])] = 4
    return classes

# ----- dosyaları bul
B5_BEFORE = pick("*Band5*Haziran*.TIF")
B7_BEFORE = pick("*Band7*Haziran*.TIF")
B5_AFTER  = pick("*Band5*Temmuz*.TIF")
B7_AFTER  = pick("*Band7*Temmuz*.TIF")

# referans grid = B5_BEFORE
with rasterio.open(B5_BEFORE) as ref:
    ref_prof = ref.profile
    ref_transform = ref.transform
    ref_shape = ref.shape
    # piksel alanı (m2)
    pix_area = abs(ref_transform.a * ref_transform.e)

nir_b, _, _, _, _ = read_and_align(B5_BEFORE)
sw2_b, _, _, _, _ = read_and_align(B7_BEFORE, ref_prof, ref_transform, ref_shape)
nir_a, _, _, _, _ = read_and_align(B5_AFTER,  ref_prof, ref_transform, ref_shape)
sw2_a, _, _, _, _ = read_and_align(B7_AFTER,  ref_prof, ref_transform, ref_shape)

# --- NBR before/after ve dNBR
nbr_before = safe_div(nir_b, sw2_b)
nbr_after  = safe_div(nir_a, sw2_a)
dnbr = nbr_before - nbr_after
classes = classify_5(dnbr)

# ---------- görseller ----------
# 1) NBR öncesi & sonrası
fig, ax = plt.subplots(1,2, figsize=(16,6))
im0 = ax[0].imshow(nbr_before, vmin=-1, vmax=1, cmap="BrBG")
ax[0].set_title("NBR Öncesi"); ax[0].axis("off")
cbar0 = fig.colorbar(im0, ax=ax[0], fraction=0.046, pad=0.04)
im1 = ax[1].imshow(nbr_after, vmin=-1, vmax=1, cmap="BrBG")
ax[1].set_title("NBR Sonrası"); ax[1].axis("off")
cbar1 = fig.colorbar(im1, ax=ax[1], fraction=0.046, pad=0.04)
plt.tight_layout(); plt.savefig(os.path.join(OUT,"nbr_before_after.png"), dpi=200); plt.close()

# 2) dNBR histogram
plt.figure(figsize=(8,6))
plt.hist(dnbr[np.isfinite(dnbr)].ravel(), bins=120)
plt.title("dNBR Histogram"); plt.xlabel("dNBR"); plt.ylabel("Piksel sayısı")
plt.tight_layout(); plt.savefig(os.path.join(OUT,"dnbr_hist.png"), dpi=200); plt.close()

# 3) 5 sınıf quicklook
colors = {
    0:(190,190,190),  # gri
    1:(255,215,0),    # sarı
    2:(255,140,0),    # turuncu
    3:(220,20,60),    # kırmızı
    4:(128,0,0)       # koyu kırmızı
}
rgb = np.zeros((classes.shape[0], classes.shape[1], 3), dtype=np.uint8)
for k,c in colors.items(): rgb[classes==k] = c
plt.figure(figsize=(9,7))
plt.imshow(rgb); plt.axis("off"); plt.title("dNBR Sınıfları (0–4)")
import matplotlib.patches as mpatches
legend = [
    mpatches.Patch(color=np.array(colors[4])/255, label="4 Yüksek"),
    mpatches.Patch(color=np.array(colors[3])/255, label="3 Orta-Yüksek"),
    mpatches.Patch(color=np.array(colors[2])/255, label="2 Orta-Düşük"),
    mpatches.Patch(color=np.array(colors[1])/255, label="1 Düşük"),
    mpatches.Patch(color=np.array(colors[0])/255, label="0 Etkilenmemiş"),
]
plt.legend(handles=legend, loc="lower right")
plt.tight_layout(); plt.savefig(os.path.join(OUT,"dnbr_classes_5.png"), dpi=200); plt.close()

# ---------- sınıf özetleri ----------
labels = {0:"Etkilenmemiş",1:"Düşük",2:"Orta-Düşük",3:"Orta-Yüksek",4:"Yüksek"}
print("\nSınıf piksel sayısı ve alan (hektar):")
for k in range(5):
    cnt = int(np.sum(classes==k))
    ha  = cnt * pix_area / 10000.0
    print(f"  {k}: {cnt} px  |  {ha:.1f} ha")
