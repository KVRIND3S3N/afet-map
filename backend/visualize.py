import rasterio
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

# Dosyayı oku
with rasterio.open("outputs/dNBR_classes.tif") as src:
    arr = src.read(1)

# Renk paleti tanımla
# 0 = gri, 1 = sarı, 2 = turuncu, 3 = kırmızı
colors = ["lightgray", "yellow", "orange", "red"]
cmap = ListedColormap(colors)

# Görselleştir
plt.figure(figsize=(10, 8))
im = plt.imshow(arr, cmap=cmap, vmin=0, vmax=3)
cbar = plt.colorbar(im, ticks=[0, 1, 2, 3])
cbar.ax.set_yticklabels(["Etkilenmemiş", "Hafif", "Orta", "Ağır"])
plt.title("Yangın Sonrası dNBR Sınıfları")
plt.axis("off")
plt.show()
