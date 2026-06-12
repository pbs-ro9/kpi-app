"""
db.py — Query functions untuk Dashboard KPI BSI Kalimantan
"""

import streamlit as st
import mysql.connector
from mysql.connector import Error
from contextlib import contextmanager
from sqlalchemy import create_engine

# ====================================================================
# KONFIGURASI KONEKSI
# ====================================================================
DB_CONFIG = {
    "host": st.secrets["mysql"]["host"],
    "user": st.secrets["mysql"]["user"],
    "password": st.secrets["mysql"]["password"],
    "database": st.secrets["mysql"]["database"],
    "port": st.secrets["mysql"]["port"],
    "charset": st.secrets["mysql"]["charset"]
}

# SQLAlchemy engine (digunakan oleh pd.read_sql agar tidak warning)
_SQLALCHEMY_URL = (
    f"mysql+mysqlconnector://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
    f"@{DB_CONFIG['host']}/{DB_CONFIG['database']}?charset={DB_CONFIG['charset']}"
)
_engine = create_engine(_SQLALCHEMY_URL)


def get_engine():
    """Return SQLAlchemy engine — untuk pd.read_sql()."""
    return _engine

# ====================================================================
# HELPER
# ====================================================================

@contextmanager
def get_connection():
    """mysql.connector connection — untuk cursor INSERT/UPDATE."""
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        yield conn
    except Error as e:
        raise RuntimeError(f"Gagal koneksi ke database: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()


def query(sql: str, params: tuple = (), one: bool = False):
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        result = cursor.fetchone() if one else cursor.fetchall()
        cursor.close()
    return result or ({} if one else [])


# ====================================================================
# 1. CABANG & AREA
# ====================================================================

def fetch_branches():
    """
    Semua cabang beserta area dan condition_id-nya.
    Return: [{ branch_id, branch_name, kdo_bsi, area_id, area_name, condition_id }]
    """
    sql = """
        SELECT b.branch_id, b.branch_name, b.kdo_bsi,
               b.area_id, a.area_name, b.condition_id
        FROM   branches b
        JOIN   areas    a ON b.area_id = a.area_id
        ORDER  BY a.area_name, b.branch_name
    """
    return query(sql)


def fetch_branch_by_id(branch_id: int):
    sql = """
        SELECT b.branch_id, b.branch_name, b.kdo_bsi,
               b.area_id, a.area_name, b.condition_id
        FROM   branches b
        JOIN   areas    a ON b.area_id = a.area_id
        WHERE  b.branch_id = %s
    """
    return query(sql, (branch_id,), one=True)


def fetch_cabang():
    return fetch_branches()


# ====================================================================
# 2. PERIODE
# ====================================================================

def fetch_available_periods():
    """
    Periode yang sudah memiliki kpi_score_records.
    Return: ['2026-03-01', ...] sebagai string, urut terbaru.
    """
    sql = """
        SELECT DISTINCT periode
        FROM   kpi_score_records
        WHERE  entity_type = 'branch'
        ORDER  BY periode DESC
    """
    rows = query(sql)
    return [str(r["periode"]) for r in rows]


# ====================================================================
# 3. TOTAL SKOR
# ====================================================================

def fetch_total_score(branch_id: int, periode: str):
    """
    Total skor KPI cabang untuk satu periode + delta vs periode sebelumnya.
    Return: { total_score, prev_score, delta_pct }
    """
    current = query(
        """
        SELECT total_score FROM kpi_score_records
        WHERE  entity_id = %s AND periode = %s
        """,
        (branch_id, periode),
        one=True,
    )

    prev_row = query(
        """
        SELECT total_score, periode
        FROM   kpi_score_records
        WHERE  entity_id = %s AND periode < %s
        ORDER  BY periode DESC
        LIMIT  1
        """,
        (branch_id, periode),
        one=True,
    )

    total_score = current.get("total_score") if current else None
    prev_score  = prev_row.get("total_score") if prev_row else None

    delta_pct = None
    if total_score is not None and prev_score and prev_score != 0:
        delta_pct = ((total_score - prev_score) / prev_score) * 100

    return {
        "total_score": total_score,
        "prev_score" : prev_score,
        "delta_pct"  : delta_pct,
    }


# ====================================================================
# 4. SKOR PER KATEGORI
# ====================================================================

def fetch_category_scores(branch_id: int, periode: str):
    """
    Skor per kategori untuk satu cabang di satu periode.
    Return: [{ category_id, category_name, score, prev_score, delta_pct }]
    """
    sql = """
        SELECT
            c.category_id,
            c.category_name,
            SUM(vs.score) AS score
        FROM   variable_scores         vs
        JOIN   kpi_variables           v  ON vs.variable_id = v.variable_id
        JOIN   kpi_variable_categories c  ON v.category_id  = c.category_id
        WHERE  vs.branch_id = %s
          AND  vs.periode   = %s
          AND  vs.score     IS NOT NULL
        GROUP  BY c.category_id, c.category_name
        ORDER  BY c.category_id
    """
    current_rows = query(sql, (branch_id, periode))

    # Periode sebelumnya untuk delta
    prev_row = query(
        """
        SELECT periode FROM kpi_score_records
        WHERE  entity_id = %s AND periode < %s
        ORDER  BY periode DESC LIMIT 1
        """,
        (branch_id, periode),
        one=True,
    )
    prev_periode = str(prev_row["periode"]) if prev_row else None

    prev_scores = {}
    if prev_periode:
        prev_rows  = query(sql, (branch_id, prev_periode))
        prev_scores = {r["category_id"]: r["score"] for r in prev_rows}

    result = []
    for row in current_rows:
        prev  = prev_scores.get(row["category_id"])
        delta = None
        if row["score"] is not None and prev and prev != 0:
            delta = ((row["score"] - prev) / prev) * 100
        result.append({
            "category_id"  : row["category_id"],
            "category_name": row["category_name"],
            "score"        : row["score"],
            "prev_score"   : prev,
            "delta_pct"    : delta,
        })
    return result


def fetch_area_avg_category_scores(area_id: int, periode: str):
    """
    Rata-rata skor per kategori seluruh cabang dalam satu area.
    Return: { category_id: avg_score }
    """
    sql = """
        SELECT
            c.category_id,
            AVG(branch_cat.score) AS avg_score
        FROM (
            SELECT
                vs.branch_id,
                v.category_id,
                SUM(vs.score) AS score
            FROM  variable_scores          vs
            JOIN  kpi_variables            v ON vs.variable_id = v.variable_id
            JOIN  branches                 b ON vs.branch_id   = b.branch_id
            WHERE b.area_id  = %s
              AND vs.periode  = %s
              AND vs.score    IS NOT NULL
            GROUP BY vs.branch_id, v.category_id
        ) branch_cat
        JOIN kpi_variable_categories c ON branch_cat.category_id = c.category_id
        GROUP BY c.category_id
    """
    rows = query(sql, (area_id, periode))
    return {r["category_id"]: r["avg_score"] for r in rows}


# ====================================================================
# 5. HISTORY SKOR (untuk chart)
# ====================================================================

def fetch_score_history(branch_id: int, limit: int = 7):
    """
    Riwayat total_score cabang N periode terakhir, urut lama → baru.
    Return: [{ periode, total_score }]
    """
    sql = """
        SELECT periode, total_score
        FROM   kpi_score_records
        WHERE  entity_id = %s
        ORDER  BY periode DESC
        LIMIT  %s
    """
    rows = query(sql, (branch_id, limit))
    # Konversi periode ke string dan balik urutan
    for r in rows:
        r["periode"] = str(r["periode"])
    return list(reversed(rows))


# ====================================================================
# 6. DETAIL VARIABEL (untuk tabel bawah)
# ====================================================================

def fetch_variable_scores(branch_id: int, periode: str):
    """
    Detail skor per variabel untuk satu cabang di satu periode.
    Return: [{
        category_id, category_name,
        variable_id, var_name, var_code, unit, type,
        realization_used, target_used, pencapaian,
        weight_used, score, formula_type_used
    }]
    """
    sql = """
        SELECT
            c.category_id,
            c.category_name,
            v.variable_id,
            v.var_name,
            v.var_code,
            v.unit,
            v.type,
            vs.realization_used,
            vs.target_used,
            vs.pencapaian,
            vs.weight_used,
            vs.score,
            vs.formula_type_used
        FROM   variable_scores         vs
        JOIN   kpi_variables           v  ON vs.variable_id = v.variable_id
        JOIN   kpi_variable_categories c  ON v.category_id  = c.category_id
        JOIN variable_configs vc ON vc.variable_id = vs.variable_id  
        WHERE vc.is_displayed = 1 AND  vs.branch_id = %s
          AND  vs.periode   = %s 
        ORDER  BY c.category_id, v.variable_id
    """
    return query(sql, (branch_id, periode))


def fetch_kpi_detail():
    """
    Fallback: daftar variabel + formula_type tanpa filter branch/periode.
    Dipakai jika belum ada data variable_scores.
    """
    sql = """
SELECT
    c.category_name AS key_result_name,
    v.variable_id,
    v.var_name,
    v.var_code,
    vc.formula_type
    FROM kpi_variables v
    JOIN kpi_variable_categories c
        ON v.category_id = c.category_id
    JOIN variable_configs vc
        ON vc.variable_id = v.variable_id
    WHERE vc.is_displayed = 1
    ORDER BY c.category_id, v.variable_id
    """
    return query(sql)


def fetch_kpi_variables():
    sql = """
        SELECT v.*, c.category_name
        FROM   kpi_variables v
        JOIN   kpi_variable_categories c ON v.category_id = c.category_id
        ORDER  BY c.category_id, v.variable_id
    """
    return query(sql)


# ====================================================================
# 7. BOBOT PER CABANG (untuk kalkulasi)
# ====================================================================

def fetch_weight_for_branch(branch_id: int, periode: str):
    """
    Ambil bobot per variabel untuk satu cabang berdasarkan condition_id-nya.
    Return: { config_id: weight }
    """
    sql = """
        SELECT vcw.config_id, vcw.weight
        FROM   variable_config_weights vcw
        JOIN   branches                b  ON b.condition_id = vcw.condition_id
        JOIN   variable_configs        vc ON vc.config_id   = vcw.config_id
        WHERE  b.branch_id  = %s
          AND  vc.periode   = %s
    """
    rows = query(sql, (branch_id, periode))
    return {r["config_id"]: r["weight"] for r in rows}