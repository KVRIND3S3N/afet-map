# SIRIUS – Afet Harita Uygulaması

TEKNOFEST Geleceğin Sürdürülebilir Şehirleri Hackathonu için geliştirilmiştir.  
Aşağıda **demo**, **kurulum** ve **.env** bilgileri yer alır.

## 🔗 Bağlantılar
- **GitHub Repo:** (https://github.com/KVRIND3S3N/afet-map)



## 🧱 Proje Yapısı
repo-kök/
├─ backend/ # API (Python + Flask)
├─ public/ # statik dosyalar (ör. SIRIUS.png)
├─ src/ # frontend (Vite + React)
├─ index.html
├─ package.json # Vite React için


---

## ✨ Özellikler
- Harita üzerinde yangın alanları (GeoJSON) ve rotalama
- “Ağaçlandırma önceliği” modu (renklendirme + legend)
- Toplanma alanı yakınlığına göre dinamik skor
- *React + Leaflet* ile hızlı arayüz (Vite)

---

## 🧪 API Uçları
Frontend şu uçları çağırır:
- `GET /api/burn-areas?mode=polys` → **GeoJSON** (yanık poligonları)
- `GET /api/assembly-areas?bbox=minX,minY,maxX,maxY` → **GeoJSON** (toplanma alanları)
- `GET /api/route-to-fire?lat=..&lon=..` → **FeatureCollection** (origin/destination/line)
- `GET /api/route-to-assembly?lat=..&lon=..` → **FeatureCollection**

> Rota için `features[].properties.role ∈ {origin, destination, line}` ve  
> `line.properties.distance_km|distance_m` alanları beklenir.

---

## ⚙️ Çevresel Değişkenler (.env)
- Frontend için `.env.sample` (opsiyonel) kök dizinde yer alır.  
- Backend için `backend/.env.sample` dosyası eklenmiştir.


---

## 🧰 Versiyonlar
- **Node.js (frontend için):** 18.x veya 20.x  
- **Python (backend için):** 3.10+  
- **Paket yöneticisi:** npm (frontend), pip (backend)

---

## 🚀 Kurulum ve Çalıştırma

### Frontend (React + Vite)
```bash
npm install
npm run dev

---

### Backend (Python + Flask)

cd backend
pip install -r requirements.txt
python app.py

## 🗄️ Veritabanı (PostgreSQL + PostGIS)

- Uygulama **PostgreSQL 14+** ve **PostGIS** eklentisi ile çalışır.  
- Veritabanı adı: `afet` (örnek)  
- Gerekli tablolar:
  - `burn_polys` → yangın alanları (geometry sütunu: `geometry`)
  - `assembly_areas` → toplanma alanları (geometry sütunu: `geometry`)

  ### Veri yükleme
Backend klasöründe veri yüklemek için yardımcı scriptler mevcuttur:
- `load_burn_polys_to_pg.py` → Yanık alanlarını PostGIS'e yükler  
- `csv2geojson_izmir.py` → CSV verisini GeoJSON’a dönüştürür  


## ⚙️ Ortam Değişkenleri

- Backend klasöründe bir `.env.sample` dosyası vardır.  
- Bu dosyayı kopyalayıp `.env` olarak adlandırın.  
- İçindeki değerleri kendi bilgisayarınıza uygun olacak şekilde düzenleyin.  

Örnek (`backend/.env.sample`):
