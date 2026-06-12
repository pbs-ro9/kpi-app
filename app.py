import sys
print(sys.version)

import streamlit as st
import plotly.graph_objects as go
from collections import OrderedDict
from services.calculation_service import calculate_period

from db import (
    fetch_branches,
    fetch_available_periods,
    fetch_total_score,
    fetch_category_scores,
    fetch_area_avg_category_scores,
    fetch_score_history,
    fetch_variable_scores,
    fetch_kpi_detail,
)
from views.import_kpi import show_import

st.set_page_config(layout="wide", page_title="Dashboard KPI", page_icon="🏦")

# ====================================================================
# SESSION STATE
# ====================================================================
if "selected_branch_id" not in st.session_state:
    st.session_state.selected_branch_id = None
if "selected_branch_name" not in st.session_state:
    st.session_state.selected_branch_name = None
if "selected_periode" not in st.session_state:
    st.session_state.selected_periode = None
if "show_cabang_dd" not in st.session_state:
    st.session_state.show_cabang_dd = False
if "page" not in st.session_state:
    st.session_state.page = "dashboard"

# ====================================================================
# ROUTING
# ====================================================================
if st.session_state.page == "import":
    # ── Verifikasi password sebelum masuk fitur Import ──
    if "import_authenticated" not in st.session_state:
        st.session_state.import_authenticated = False

    if not st.session_state.import_authenticated:
        st.markdown("""
        <style>
            .auth-container {
                max-width: 420px;
                margin: 80px auto;
                padding: 40px 36px;
                background: var(--bg-card, #fff);
                border: 1px solid var(--border-card, #f0f2f5);
                border-radius: 16px;
                box-shadow: 0 4px 24px rgba(0,0,0,0.08);
                text-align: center;
            }
            .auth-icon { font-size: 48px; margin-bottom: 12px; }
            .auth-title { font-size: 20px; font-weight: 700; color: var(--text-primary, #1a1a2e); margin-bottom: 4px; }
            .auth-subtitle { font-size: 13px; color: var(--text-muted, #8c8c8c); margin-bottom: 24px; }
            .back-link {
            display: inline-block;
            margin-bottom: 20px;
            color: #1677ff;
            font-size: 13px;
            font-weight: 500;
            text-decoration: none;
            cursor: pointer;
            transition: color 0.2s;
        }

        .back-link:hover {
            color: #0958d9;
        }

        </style>
        """, unsafe_allow_html=True)

        st.markdown('<a class="back-link" href="/" target="_self">← Kembali ke Dashboard</a>', unsafe_allow_html=True)

        st.markdown("""
        <div class="auth-container">
            <div class="auth-icon">🔒</div>
            <div class="auth-title">Akses Terbatas</div>
            <div class="auth-subtitle">Masukkan password untuk mengakses fitur Import</div>
        </div>
        """, unsafe_allow_html=True)        

        col_pad_l, col_input, col_pad_r = st.columns([1.5, 1, 1.5])
        with col_input:
            pwd = st.text_input("Password", type="password", key="import_pwd_input", label_visibility="collapsed")
            if st.button("🔓 Masuk", use_container_width=True, type="primary"):
                if pwd == st.secrets["app"]["import_password"]:
                    st.session_state.import_authenticated = True
                    st.rerun()
                else:
                    st.error("Password salah!")
        st.stop()

    show_import()
    st.stop()

# ====================================================================
# LOAD DATA MASTER (cached agar tidak re-query tiap rerun)
# ====================================================================
@st.cache_data(ttl=60)
def load_branches():
    return fetch_branches()

@st.cache_data(ttl=60)
def load_periods():
    return fetch_available_periods()

branches   = load_branches()
periods    = load_periods()

# Default pilihan pertama
branch_map = {b["branch_id"]: b for b in branches}
branch_ids = [b["branch_id"] for b in branches]

if st.session_state.selected_branch_id not in branch_ids and branch_ids:
    st.session_state.selected_branch_id   = branch_ids[0]
    st.session_state.selected_branch_name = branches[0]["branch_name"]

if st.session_state.selected_periode not in periods and periods:
    st.session_state.selected_periode = periods[0]

# Cabang & periode aktif
active_branch  = branch_map.get(st.session_state.selected_branch_id, {})
active_periode = st.session_state.selected_periode

# ====================================================================
# CUSTOM CSS
# ====================================================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

    :root {
        --bg-body: #f5f6fa;
        --bg-card: #fff;
        --bg-card-hover-shadow: rgba(22,119,255,0.10);
        --text-primary: #1a1a2e;
        --text-secondary: #262626;
        --text-muted: #8c8c8c;
        --text-soft: #595959;
        --border-card: #f0f2f5;
        --border-light: #f0f0f0;
        --border-input: #d9d9d9;
        --border-dropdown: #e8e8e8;
        --shadow-card: 0 1px 4px rgba(0,0,0,0.05);
        --shadow-dropdown: 0 12px 40px rgba(0,0,0,0.13);
        --dd-hover: #f0f7ff;
        --dd-active: #eff6ff;
        --hr-color: #f0f0f0;
        --cat-header-bg: #fafafa;
        --delta-pos-bg: #f6ffed;  --delta-pos-border: #b7eb8f;
        --delta-neg-bg: #fff2f0;  --delta-neg-border: #ffccc7;
        --col-blue-head: #e8f4fd;   --col-blue-cell: #f0f8ff;
        --col-orange-head: #fff7e6; --col-orange-cell: #fffbe6;
        --col-green-head: #f6ffed;  --col-green-cell: #f6ffed;
        --col-purple-head: #f9f0ff; --col-purple-cell: #f9f0ff;
        --col-red-head: #fff1f0;    --col-red-cell: #fff1f0;
        --grid-line: #f5f5f5;
    }

    @media (prefers-color-scheme: dark) {
        :root {
            --bg-body: #0e1117;
            --bg-card: #1a1d24;
            --bg-card-hover-shadow: rgba(22,119,255,0.20);
            --text-primary: #e6e8ec;
            --text-secondary: #cfd2d6;
            --text-muted: #8b8fa3;
            --text-soft: #a0a4b0;
            --border-card: #2a2d35;
            --border-light: #2a2d35;
            --border-input: #3a3d45;
            --border-dropdown: #2a2d35;
            --shadow-card: 0 1px 6px rgba(0,0,0,0.30);
            --shadow-dropdown: 0 12px 40px rgba(0,0,0,0.50);
            --dd-hover: #1c2636;
            --dd-active: #17253a;
            --hr-color: #2a2d35;
            --cat-header-bg: #1e2128;
            --delta-pos-bg: #162312;  --delta-pos-border: #274916;
            --delta-neg-bg: #2a1215;  --delta-neg-border: #58181c;
            --col-blue-head: #111d2c;   --col-blue-cell: #111d2c;
            --col-orange-head: #2b1d11; --col-orange-cell: #2b1d11;
            --col-green-head: #162312;  --col-green-cell: #162312;
            --col-purple-head: #1a1325; --col-purple-cell: #1a1325;
            --col-red-head: #2a1215;    --col-red-cell: #2a1215;
            --grid-line: #262930;
        }
        .stApp, .main, [data-testid="stAppViewContainer"],
        [data-testid="stHeader"], [data-testid="stToolbar"] {
            background-color: var(--bg-body) !important;
        }
        .stSelectbox > div > div, [data-baseweb="select"] > div {
            background-color: var(--bg-card) !important;
            color: var(--text-secondary) !important;
            border-color: var(--border-input) !important;
        }
        [data-baseweb="menu"] { background-color: var(--bg-card) !important; }
        [data-baseweb="menu"] li { color: var(--text-secondary) !important; }
        [data-baseweb="menu"] li:hover { background-color: var(--dd-hover) !important; }
    }

    html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif; background-color: var(--bg-body); }
    .stApp { background-color: var(--bg-body); }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .main .block-container { padding-top: 2rem; padding-left: 2.5rem; padding-right: 2.5rem; max-width: 100%; }

    [data-testid="stButton"] > button[kind="secondary"] {
        background: transparent !important; border: none !important;
        padding: 0 4px !important; font-size: 24px !important; font-weight: 700 !important;
        color: var(--text-primary) !important; box-shadow: none !important;
        text-align: left !important; line-height: 1.2 !important; cursor: pointer !important;
    }
    [data-testid="stButton"] > button[kind="secondary"]:hover {
        color: #1677ff !important; background: transparent !important;
    }

    .cabang-dropdown {
        background: var(--bg-card); border: 1px solid var(--border-dropdown);
        border-radius: 14px; padding: 8px;
        box-shadow: var(--shadow-dropdown); min-width: 260px;
    }
    .cabang-dd-header {
        font-size: 10px; font-weight: 700; color: var(--text-muted);
        text-transform: uppercase; letter-spacing: 0.8px;
        padding: 6px 10px 10px 10px;
        border-bottom: 1px solid var(--border-light); margin-bottom: 6px;
    }
    .cabang-dd-area {
        font-size: 10px; font-weight: 700; color: var(--text-muted);
        text-transform: uppercase; letter-spacing: 0.6px;
        padding: 8px 10px 4px 10px;
    }
    .cabang-dd-item {
        display: flex; align-items: center; justify-content: space-between;
        padding: 9px 12px; border-radius: 8px;
        font-size: 13px; color: var(--text-secondary); cursor: pointer;
        transition: background 0.15s;
    }
    .cabang-dd-item:hover { background: var(--dd-hover); color: #1677ff; }
    .cabang-dd-item-active { background: var(--dd-active); color: #1677ff; font-weight: 600; }
    .cabang-dd-check { color: #1677ff; font-size: 13px; }

    .kpi-card {
        background: var(--bg-card); border: 1px solid var(--border-card);
        border-radius: 12px; padding: 18px 20px;
        box-shadow: var(--shadow-card); transition: box-shadow 0.2s;
    }
    .kpi-card:hover { box-shadow: 0 4px 16px var(--bg-card-hover-shadow); }
    .kpi-label { font-size: 12px; color: var(--text-muted); font-weight: 500; margin-bottom: 6px; }
    .kpi-value { font-size: 26px; font-weight: 700; color: var(--text-primary); line-height: 1.2; margin-bottom: 6px; }
    .kpi-delta-pos { font-size: 12px; color: #52c41a; font-weight: 600; background: var(--delta-pos-bg); border: 1px solid var(--delta-pos-border); border-radius: 20px; padding: 2px 8px; display: inline-block; }
    .kpi-delta-neg { font-size: 12px; color: #ff4d4f; font-weight: 600; background: var(--delta-neg-bg); border: 1px solid var(--delta-neg-border); border-radius: 20px; padding: 2px 8px; display: inline-block; }
    .kpi-delta-neutral { font-size: 12px; color: var(--text-muted); font-weight: 500; padding: 2px 0px; display: inline-block; }

    .section-card { background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 12px; padding: 20px 24px; box-shadow: var(--shadow-card); height: 100%; }
    .stButton > button { border-radius: 8px; font-size: 13px; font-weight: 500; padding: 6px 16px; border: 1px solid var(--border-input); background: var(--bg-card); color: var(--text-soft); transition: all 0.2s; }
    .stButton > button:hover { border-color: #1677ff; color: #1677ff; }

    .kpi-detail-table th {
        background: var(--cat-header-bg);
    }
    .key-result-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .key-result-table th { font-size: 11px; color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; padding: 8px 12px; border-bottom: 1px solid var(--border-light); text-align: left; }
    .key-result-table td { padding: 10px 12px; border-bottom: 1px solid var(--border-light); color: var(--text-secondary); font-size: 13px; }
    .key-result-table tr:last-child td { border-bottom: none; }
    .score-green { color: #52c41a; font-weight: 600; }
    .score-red   { color: #ff4d4f; font-weight: 600; }
    .score-blue  { color: #1677ff; font-weight: 600; }

    .kpi-table-wrapper { background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 12px; padding: 20px 24px; box-shadow: var(--shadow-card); }
    .kpi-detail-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .kpi-detail-table th { font-size: 11px; color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; padding: 10px 10px; text-align: right; }
    .kpi-detail-table th:first-child, .kpi-detail-table th:nth-child(2) { text-align: left; }
    .kpi-detail-table td { padding: 10px 10px; border-top: 1px solid var(--border-light); color: var(--text-secondary); vertical-align: middle; text-align: right; }
    .kpi-detail-table td:first-child { text-align: center; color: var(--text-muted); width: 30px; }
    .kpi-detail-table td:nth-child(2) { text-align: left; }
   .category-header td {
    background: #f8f9fa !important;

    color: #262626 !important;

    font-size: 13px !important;

    font-weight: 700 !important;

    text-transform: uppercase;

    text-align: left !important;

    border-top: 2px solid #d9d9d9 !important;

    border-bottom: 1px solid #e8e8e8 !important;
    
    
}

    .kpi-detail-table th:nth-child(1),
    .kpi-detail-table th:nth-child(2),
    .kpi-detail-table th:nth-child(3),
    .kpi-detail-table th:nth-child(4),
    .kpi-detail-table th:nth-child(5),
    .kpi-detail-table th:nth-child(6),
    .kpi-detail-table th:nth-child(7) {
        background: #e8f8f5;
        color: #262626 !important;
        font-weight: 600;
    } 
    .kpi-detail-table tr:not(.category-header) td {
        background: var(--bg-card);
    }

    .tab-active { background: #1677ff; color: white; border-radius: 6px; padding: 4px 14px; font-size: 13px; font-weight: 600; display: inline-block; }
    .tab-inactive { color: var(--text-soft); padding: 4px 14px; font-size: 13px; display: inline-block; cursor: pointer; }
    hr { border: none; border-top: 1px solid var(--hr-color); margin: 16px 0; }
    div[data-testid="stDataFrame"] { display: none; }
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    
    .badge-green {
    background: #f6ffed;
    color: #389e0d;
    border: 1px solid #b7eb8f;
    border-radius: 999px;
    padding: 3px 10px;
    font-weight: 700;
    font-size: 12px;
}

.badge-yellow {
    background: #fffbe6;
    color: #d48806;
    border: 1px solid #ffe58f;
    border-radius: 999px;
    padding: 3px 10px;
    font-weight: 700;
    font-size: 12px;
}

.badge-red {
    background: #fff1f0;
    color: #cf1322;
    border: 1px solid #ffa39e;
    border-radius: 999px;
    padding: 3px 10px;
    font-weight: 700;
    font-size: 12px;
}
</style>
""", unsafe_allow_html=True)

# ====================================================================
# HELPER FORMAT
# ====================================================================

def get_pencapaian_badge(pencapaian):
    if pencapaian is None:
        return "-"

    if pencapaian < 95:
        cls = "badge-red"
    elif pencapaian < 100:
        cls = "badge-yellow"
    else:
        cls = "badge-green"

    return f'<span class="{cls}">{pencapaian:.2f}%</span>'

def get_pencapaian_color(pencapaian):
    if pencapaian is None:
        return "inherit"

    if pencapaian < 95:
        return "#ff4d4f"   # merah
    elif pencapaian >= 100:
        return "#52c41a"   # hijau
    else:
        return "#faad14"   # kuning
    
def fmt_score(val):
    """Format skor jadi string dengan 2 desimal, atau '-' jika None."""
    if val is None:
        return "-"
    return f"{val:.2f}"

def fmt_delta(delta_pct, pos_is_good=True):
    """
    Return (label, css_class) untuk delta.
    pos_is_good=False untuk variabel NEGATIF (NPF, KOL2).
    """
    if delta_pct is None:
        return "-", "kpi-delta-neutral"
    arrow = "↑" if delta_pct >= 0 else "↓"
    label = f"{arrow} {abs(delta_pct):.1f}%"
    if pos_is_good:
        css = "kpi-delta-pos" if delta_pct >= 0 else "kpi-delta-neg"
    else:
        css = "kpi-delta-neg" if delta_pct >= 0 else "kpi-delta-pos"
    return label, css

def fmt_real(val, unit=""):
    """Format nilai realisasi sesuai unit."""
    if val is None:
        return "-"
    if unit in ("RP",):
        if abs(val) >= 1e9:
            return f"{val/1e9:.2f}T"
        elif abs(val) >= 1e6:
            return f"{val/1e6:.2f}M"
        elif abs(val) >= 1e3:
            return f"{val/1e3:.2f}Jt"
        return f"{val:.2f}"
    if unit in ("%",):
        return f"{val:.2f}%"
    return f"{val:,.2f}"

# ====================================================================
# PAGE HEADER
# ====================================================================
st.markdown("""
<div style="margin-bottom:18px;">
    <span style="font-size:11px; font-weight:700; letter-spacing:1.5px; text-transform:uppercase; color:#1677ff;">🏦 BSI Regional XI</span>
    <div style="font-size:22px; font-weight:800; color:var(--text-primary, #1a1a2e); line-height:1.3;">Strategic KPI Evaluation System</div>
</div>
""", unsafe_allow_html=True)
col_title, col_calc, col_import = st.columns([5.5, 1.5, 1])

with col_title:
    btn_label = f"{active_branch.get('branch_name', 'Pilih Cabang')} ▾"
    if st.button(btn_label, key="cabang_title_btn"):
        st.session_state.show_cabang_dd = not st.session_state.show_cabang_dd

with col_calc:
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if st.button("⚙️ Hitung KPI", use_container_width=True):
        if active_periode:
            from db import get_connection
            try:
                with st.spinner("Mengkalkulasi skor..."):
                    with get_connection() as conn:
                        res = calculate_period(conn, active_periode)
                    
                    if res:
                        st.success(f"Berhasil mengkalkulasi skor KPI periode {active_periode}")
                    else:
                        st.warning(f"Tidak ada data untuk dikalkulasi pada {active_periode}")
            except Exception as e:
                st.error(f"Gagal mengkalkulasi: {e}")
        else:
            st.warning("Pilih periode terlebih dahulu")

with col_import:
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if st.button("Import"):
        st.session_state.page = "import"
        st.rerun()

# ====================================================================
# DROPDOWN CABANG (dikelompokkan per area)
# ====================================================================
if st.session_state.show_cabang_dd:
    dd_col, _ = st.columns([2, 5])
    with dd_col:
        st.markdown('<div class="cabang-dropdown">', unsafe_allow_html=True)
        st.markdown('<div class="cabang-dd-header">🏦 &nbsp; Pilih Unit Kerja</div>', unsafe_allow_html=True)

        # Kelompokkan per area
        area_groups = OrderedDict()
        for b in branches:
            area_name = b["area_name"]
            if area_name not in area_groups:
                area_groups[area_name] = []
            area_groups[area_name].append(b)

        for area_name, area_branches in area_groups.items():
            st.markdown(f'<div class="cabang-dd-area">📍 {area_name}</div>', unsafe_allow_html=True)
            for b in area_branches:
                is_active = b["branch_id"] == st.session_state.selected_branch_id
                css_class = "cabang-dd-item cabang-dd-item-active" if is_active else "cabang-dd-item"
                check = "✓" if is_active else ""
                st.markdown(
                    f'<div class="{css_class}" style="margin-bottom:2px;">'
                    f'<span>{b["branch_name"]}</span>'
                    f'<span class="cabang-dd-check">{check}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button(b["branch_name"], key=f"dd_{b['branch_id']}", use_container_width=True):
                    st.session_state.selected_branch_id   = b["branch_id"]
                    st.session_state.selected_branch_name = b["branch_name"]
                    st.session_state.show_cabang_dd = False
                    st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ====================================================================
# FILTER — PERIODE
# ====================================================================
fc1, _ = st.columns([0.5, 3])
with fc1:
    if periods:
        selected_idx = periods.index(active_periode) if active_periode in periods else 0
        chosen = st.selectbox(
            "",
            options=periods,
            index=selected_idx,
            label_visibility="collapsed",
            key="periode_select",
        )
        if chosen != st.session_state.selected_periode:
            st.session_state.selected_periode = chosen
            active_periode = chosen
            st.rerun()
    else:
        st.markdown(
            "<div style='padding:8px;color:var(--text-muted);font-size:13px;'>Belum ada data periode</div>",
            unsafe_allow_html=True,
        )

st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# ====================================================================
# LOAD DATA DINAMIS untuk branch & periode aktif
# ====================================================================
branch_id     = st.session_state.selected_branch_id
area_id       = active_branch.get("area_id")

if not branch_id or not active_periode:
    st.info("Pilih cabang dan periode untuk melihat data.")
    st.stop()

@st.cache_data(ttl=30)
def load_dashboard_data(branch_id, area_id, periode):
    total    = fetch_total_score(branch_id, periode)
    cat_scores = fetch_category_scores(branch_id, periode)
    area_avg   = fetch_area_avg_category_scores(area_id, periode) if area_id else {}
    history    = fetch_score_history(branch_id, limit=7)
    var_scores = fetch_variable_scores(branch_id, periode)
    return total, cat_scores, area_avg, history, var_scores

total_data, cat_scores, area_avg, history, var_scores = load_dashboard_data(
    branch_id, area_id, active_periode
)

# ====================================================================
# KPI CARDS
# ====================================================================
# Kartu 1: Total Score
# Kartu 2-5: Skor per kategori (maks 4 kategori)
cards = []

# Total score
total_score = total_data.get("total_score")
total_delta, total_css = fmt_delta(total_data.get("delta_pct"))
cards.append({
    "label": "Total Score KPI",
    "value": fmt_score(total_score),
    "delta": total_delta,
    "css"  : total_css,
})

# Per kategori
for cat in cat_scores:
    cat_delta, cat_css = fmt_delta(cat.get("delta_pct"))
    cards.append({
        "label": cat["category_name"].title(),
        "value": fmt_score(cat.get("score")),
        "delta": cat_delta,
        "css"  : cat_css,
    })

# Pastikan selalu 5 kartu (pad dengan kosong jika kategori < 4)
while len(cards) < 5:
    cards.append({"label": "-", "value": "-", "delta": "-", "css": "kpi-delta-neutral"})
cards = cards[:5]

k_cols = st.columns(5, gap="small")
for i, kpi in enumerate(cards):
    with k_cols[i]:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">{kpi['label']}</div>
            <div class="kpi-value">{kpi['value']}</div>
            <span class="{kpi['css']}">{kpi['delta']}</span>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# ====================================================================
# GROWTH CHART + KEY RESULT TABLE
# ====================================================================
col_chart, col_table = st.columns([2, 1], gap="medium")

with col_chart:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("""
    <div style="display:flex;align-items:center;gap:4px;margin-bottom:16px;">
        <span style="font-weight:700;font-size:15px;color:var(--text-primary);margin-right:12px;">Growth Performance</span>
        <span class="tab-active">Total Score</span>
    </div>
    """, unsafe_allow_html=True)

    if history:
        x_labels = [r["periode"] for r in history]
        y_values = [r["total_score"] if r["total_score"] is not None else 0 for r in history]
    else:
        x_labels = [active_periode]
        y_values = [total_score or 0]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_labels, y=y_values,
        mode='lines+markers',
        line=dict(color='#1677ff', width=2.5, shape='spline'),
        marker=dict(size=6, color='#1677ff', line=dict(width=2, color='white')),
        fill='tozeroy', fillcolor='rgba(22,119,255,0.08)',
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        height=220,
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=11, color='#8c8c8c')),
        yaxis=dict(showgrid=True, gridcolor='#f5f5f5', zeroline=False, tickfont=dict(size=11, color='#8c8c8c'), nticks=6),
        hovermode='x unified',
        hoverlabel=dict(bgcolor='#1677ff', font_color='white', bordercolor='#1677ff'),
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    st.markdown('</div>', unsafe_allow_html=True)

with col_table:
    rows_html = ""
    for i, cat in enumerate(cat_scores, 1):
        score_val = cat.get("score")
        avg_val   = area_avg.get(cat["category_id"])
        # Warna: hijau jika >= avg, merah jika < avg
        if score_val is not None and avg_val is not None:
            color_class = "score-green" if score_val >= avg_val else "score-red"
        else:
            color_class = "score-blue"
        rows_html += f"""
        <tr>
            <td style="color:var(--text-muted);">{i}</td>
            <td>{cat['category_name'].title()}</td>
            <td class="{color_class}">{fmt_score(score_val)}</td>
            <td>{fmt_score(avg_val)}</td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:20px;">Belum ada data</td></tr>'

    st.markdown(f"""
    <div class="section-card">
        <div style="font-weight:700;font-size:15px;color:var(--text-primary);margin-bottom:14px;">Key Result Cabang</div>
        <table class="key-result-table">
            <thead><tr>
                <th>#</th><th>Key Result</th><th>Skor Cabang</th><th>Avg Area</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# ====================================================================
# KPI DETAIL TABLE
# ====================================================================
if var_scores:
    # Kelompokkan per kategori dari variable_scores
    category_groups = OrderedDict()
    for row in var_scores:
        cat_name = row["category_name"]
        if cat_name not in category_groups:
            category_groups[cat_name] = []
        category_groups[cat_name].append(row)
else:
    # Fallback: tampilkan variabel tanpa skor jika belum ada kalkulasi
    fallback = fetch_kpi_detail()
    category_groups = OrderedDict()
    for row in fallback:
        cat_name = row["key_result_name"]
        if cat_name not in category_groups:
            category_groups[cat_name] = []
        category_groups[cat_name].append(row)

tbody_html = ""
for cat_name, variables in category_groups.items():
    tbody_html += f'<tr class="category-header"><td colspan="7"># &nbsp; {cat_name.title()}</td></tr>\n'
    for idx, var in enumerate(variables, 1):
        # Ambil nilai dari variable_scores jika ada
        real_val    = var.get("realization_used")
        target_val  = var.get("target_used")
        pencapaian  = var.get("pencapaian")
        weight_used = var.get("weight_used") or var.get("weight")
        score_val   = var.get("score")
        unit        = var.get("unit", "")

        real_str   = fmt_real(real_val, unit) if real_val is not None else "-"
        target_str = fmt_real(target_val, unit) if target_val is not None else "-"
        pct_color = get_pencapaian_color(pencapaian)
        pct_str = get_pencapaian_badge(pencapaian)
        weight_str = f"{weight_used:.1f}%" if weight_used else "-"
        score_str  = fmt_score(score_val)

        tbody_html += (
            f'<tr>'
            f'<td>{idx}</td>'
            f'<td style="text-align:left">{var["var_name"].title()}</td>'
            f'<td>{real_str}</td>'
            f'<td>{target_str}</td>'
            f'<td>{pct_str}</td>'
            f'<td>{weight_str}</td>'
            f'<td>{score_str}</td>'
            f'</tr>\n'
        )

st.markdown(f"""
<div class="kpi-table-wrapper">
    <div style="font-weight:700;font-size:15px;color:var(--text-primary);margin-bottom:16px;">Key Performance Indikator</div>
    <table class="kpi-detail-table">
        <thead>
            <tr>
                <th>#</th>
                <th>Indikator</th>
                <th>Real/Growth</th>
                <th>Target</th>
                <th>Real %</th>
                <th>Bobot</th>
                <th>Skor</th>
            </tr>
        </thead>
        <tbody>{tbody_html}</tbody>
    </table>
</div>
""", unsafe_allow_html=True)

st.markdown("<div style='height:32px'></div>", unsafe_allow_html=True)
