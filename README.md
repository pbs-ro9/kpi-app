# 📊 Strategic KPI Evaluation System
### BSI Regional XI — Kalimantan

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-1.x-red?logo=streamlit)
![MySQL](https://img.shields.io/badge/MySQL-8.0-orange?logo=mysql)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

Sistem evaluasi KPI berbasis web untuk memantau performa cabang-cabang **Bank Syariah Indonesia (BSI) Regional XI Kalimantan**. Dibangun menggunakan Python Streamlit dengan koneksi langsung ke database MySQL.

---

## ✨ Fitur Utama

- 📈 **Dashboard KPI per Cabang** — Menampilkan Total Score KPI beserta breakdown per Key Result: Profitabilitas, Volume Bisnis & Kualitas Asset, Cust Based, dan Operational & People Development
- 📊 **Growth Performance Chart** — Visualisasi tren pertumbuhan skor dari waktu ke waktu menggunakan grafik interaktif
- 🏆 **Key Result Cabang vs Area** — Perbandingan skor cabang terhadap rata-rata area secara langsung
- 📋 **Tabel Key Performance Indikator** — Detail seluruh indikator KPI beserta nilai realisasi, target, persentase pencapaian, bobot, dan skor
- 🧮 **Hitung KPI** — Kalkulasi ulang skor KPI berdasarkan data realisasi terbaru
- 📥 **Import Data** — Upload data realisasi KPI dari file Excel ke database
- 🗓️ **Filter Periode** — Navigasi data berdasarkan periode bulan yang tersedia

---

## 🗂️ Struktur Folder

```
KPI-APP/
├── .streamlit/
│   └── secrets.toml        # Konfigurasi koneksi database (lokal)
├── services/
│   ├── calculation_service.py  # Engine kalkulasi skor KPI
│   └── formula_services.py     # Pemrosesan formula & komponen variabel
├── views/
│   └── import_kpi.py       # Halaman import data Excel
├── app.py                  # Entry point & dashboard utama
├── db.py                   # Koneksi & query MySQL
├── requirements.txt        # Dependensi Python
└── README.md
```

---

## ⚙️ Cara Running di Local

### 1. Clone Repository

```bash
git clone https://github.com/pbs-ro9/kpi-app.git
cd kpi-app
```

### 2. Buat Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

### 3. Install Dependensi

```bash
pip install -r requirements.txt
```

### 4. Konfigurasi Database

Buat file `.streamlit/secrets.toml` (jika belum ada):

```toml
[mysql]
host     = "localhost"       # atau host Hostinger kamu
port     = 3306
user     = "root"            # sesuaikan
password = "password_kamu"
database = "nama_database"
```

> ⚠️ File ini **jangan di-commit ke GitHub**. Pastikan `.streamlit/secrets.toml` sudah ada di `.gitignore`.

### 5. Jalankan Aplikasi

```bash
streamlit run app.py
```

Aplikasi akan terbuka otomatis di browser: `http://localhost:8501`

---

## 🔧 Konfigurasi Penting

### Koneksi Database (`db.py`)

Aplikasi membaca kredensial dari `st.secrets`. Pastikan struktur `DB_CONFIG` di `db.py` seperti berikut:

```python
import streamlit as st
import mysql.connector

DB_CONFIG = {
    "host"     : st.secrets["mysql"]["host"],
    "port"     : st.secrets["mysql"]["port"],
    "user"     : st.secrets["mysql"]["user"],
    "password" : st.secrets["mysql"]["password"],
    "database" : st.secrets["mysql"]["database"],
}
```

### Remote MySQL Hostinger

Agar Streamlit Cloud bisa mengakses database Hostinger, aktifkan **Remote MySQL** di hPanel:

```
hPanel → Hosting → Databases → Remote MySQL → Tambahkan: %
```

---

## 🚀 Deploy ke Streamlit Cloud

### 1. Push ke GitHub

Pastikan repository sudah ter-push ke GitHub dan branch `main` sudah up-to-date:

```bash
git add .
git commit -m "ready to deploy"
git push origin main
```

> Pastikan file `.streamlit/secrets.toml` **tidak ikut ter-push** (cek `.gitignore`)

### 2. Buat Akun & Login

Buka [streamlit.io/cloud](https://streamlit.io/cloud) dan login menggunakan akun GitHub.

### 3. Deploy App

- Klik **"New app"**
- Pilih repository: `kpi-app`
- Branch: `main`
- Main file path: `app.py`
- Klik **"Deploy!"**

### 4. Konfigurasi Secrets

Setelah deploy, masuk ke **Manage app → Settings → Secrets**, lalu isi:

```toml
[mysql]
host     = "srv1320.hstgr.io"
port     = 3306
user     = "username_db_kamu"
password = "password_db_kamu"
database = "nama_database_kamu"
```

Klik **Save** → app akan restart otomatis dan siap diakses.

---

## 📦 Requirements

```
streamlit
mysql-connector-python
pymysql
pandas
plotly
openpyxl
sqlalchemy
```

---
