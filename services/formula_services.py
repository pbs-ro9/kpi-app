"""
formula_services.py — Kalkulasi formula KPI (combine, percentation, growth)

Format DataFrame: semi-long
    kdo_bsi | var_code | {periode_col} | {baseline_col}

Opsi A: calculate_combine() menghitung SUM untuk periode_col DAN baseline_col
sekaligus dalam memory, sehingga growth bisa memakai baseline combine yang benar.

Fix chained combine: proses incremental per iterasi + multi-pass agar variabel
combine yang menjadi source variabel combine lain (misal PHE → PHE_CBR) bisa
ditemukan di realisasi_df pada iterasi berikutnya.
"""

import pandas as pd
import numpy as np


# ====================================================================
# HELPER
# ====================================================================

def _to_numeric_cols(df, cols):
    """Konversi kolom ke numerik secara in-place, return df."""
    existing = [c for c in cols if c in df.columns]
    df[existing] = df[existing].apply(pd.to_numeric, errors="coerce")
    return df


# ====================================================================
# COMBINE
# ====================================================================

def calculate_combine(
    realisasi_df,
    configs_df,
    components_df,
    variables_df,
    period_cols,
    baseline_col=None,
):
    """
    Untuk setiap config bertipe 'combine':
        target_var = sum(source_var_1, source_var_2, ...)

    [Opsi A] baseline_col ikut dijumlahkan sehingga variabel combine
    siap dipakai oleh calculate_growth() tanpa nilai NaN di baseline.

    [Fix chained combine] Diproses secara incremental per iterasi:
    setiap hasil combine langsung ditambahkan ke realisasi_df sebelum
    iterasi berikutnya berjalan. Jika source belum tersedia (karena
    bergantung pada hasil combine lain yang belum selesai), config
    tersebut diulang di pass berikutnya — sampai semua selesai atau
    tidak ada progress lagi.

    Contoh chain PHE → PHE_CBR → INDIVIDU_CUST_GROWTH:
        Pass 1, iter 1: PHE       = NoaPayroll+NoaHaji+NoaEmas  ✓  (source raw)
        Pass 1, iter 2: PHE_CBR   = PHE+CBR                     ✓  (PHE sudah ada)
        growth        : INDIVIDU  = PHE_CBR[Mar] - PHE_CBR[Des] ✓

    Tanpa fix (batch di akhir):
        iter 2: PHE_CBR mencari PHE di realisasi_df → TIDAK ADA
                → PHE_CBR = CBR saja (nilai salah) ✗
    """
    combine_configs = configs_df[configs_df["formula_type"] == "combine"]

    if combine_configs.empty:
        return realisasi_df

    # Kolom yang perlu dijumlahkan: periode + baseline (Opsi A)
    sum_cols = list(period_cols)
    if baseline_col and baseline_col not in sum_cols:
        sum_cols = sum_cols + [baseline_col]

    MAX_PASS = 10  # batas pass untuk hindari infinite loop
    remaining = combine_configs.copy()

    for pass_num in range(1, MAX_PASS + 1):
        if remaining.empty:
            break

        next_remaining = []
        made_progress  = False

        for _, config in remaining.iterrows():

            config_id          = config["config_id"]
            target_variable_id = config["variable_id"]

            target_var_row = variables_df[
                variables_df["variable_id"] == target_variable_id
            ]
            if target_var_row.empty:
                continue
            target_var_code = target_var_row.iloc[0]["var_code"]

            components = components_df[
                components_df["config_id"] == config_id
            ]
            source_ids = components["source_variable_id"].tolist()

            if not source_ids:
                continue

            source_codes = variables_df[
                variables_df["variable_id"].isin(source_ids)
            ]["var_code"].tolist()

            # Cari source di realisasi_df yang sudah diupdate
            temp = realisasi_df[
                realisasi_df["var_code"].isin(source_codes)
            ].copy()

            found_codes = temp["var_code"].unique().tolist()
            missing     = [c for c in source_codes if c not in found_codes]

            if missing:
                # Source belum tersedia — coba di pass berikutnya
                next_remaining.append(config)
                print(f"  [PASS {pass_num}] {target_var_code}: "
                      f"source {missing} belum ada, ditunda ke pass berikutnya")
                continue

            # Hitung sum per cabang untuk semua kolom
            existing_cols = [c for c in sum_cols if c in temp.columns]
            temp = _to_numeric_cols(temp, existing_cols)

            result = (
                temp.groupby(["kdo_bsi"], as_index=False)[existing_cols]
                .sum(min_count=1)
            )
            result["var_code"] = target_var_code

            # ★ Langsung tambahkan ke realisasi_df (incremental)
            # agar iterasi berikutnya bisa memakai hasilnya
            # Hapus terlebih dahulu jika var_code tersebut sudah ada di data mentah
            realisasi_df = realisasi_df[realisasi_df["var_code"] != target_var_code]

            realisasi_df = pd.concat(
                [realisasi_df, result], ignore_index=True
            )
            made_progress = True

        remaining = pd.DataFrame(next_remaining) if next_remaining else pd.DataFrame()

        if not made_progress and not remaining.empty:
            # Tidak ada progress → kemungkinan circular dependency
            unresolved = []
            for _, c in remaining.iterrows():
                var_row = variables_df[
                    variables_df["variable_id"] == c["variable_id"]
                ]
                name = var_row.iloc[0]["var_code"] if not var_row.empty else str(c["variable_id"])
                unresolved.append(name)
            print(f"  [WARN] Combine tidak bisa diselesaikan "
                  f"(circular/source tidak ada): {unresolved}")
            break

    return realisasi_df


# ====================================================================
# PERCENTATION
# ====================================================================
 
def calculate_ratio(
    realisasi_df,
    configs_df,
    components_df,
    variables_df,
    period_cols,
    baseline_col=None,
):
    """
    Untuk setiap config bertipe 'percentation':
        target_var = (numerator_var / denominator_var) * 100
    """
    ratio_rows = []
    ratio_configs = configs_df[configs_df["formula_type"] == "percentation"]
 
    calc_cols = list(period_cols)
    if baseline_col and baseline_col not in calc_cols:
        calc_cols = calc_cols + [baseline_col]
 
    for _, config in ratio_configs.iterrows():
 
        config_id          = config["config_id"]
        target_variable_id = config["variable_id"]
 
        target_var_row = variables_df[
            variables_df["variable_id"] == target_variable_id
        ]
        if target_var_row.empty:
            continue
        target_var_code = target_var_row.iloc[0]["var_code"]
        target_unit     = target_var_row.iloc[0].get("unit", None)
        # Kalikan 100 hanya jika satuan target variabel adalah '%'
        multiply_100    = (str(target_unit).strip() == "%")
 
        components = components_df[components_df["config_id"] == config_id]
        num_rows   = components[components["role"] == "numerator"]
        den_rows   = components[components["role"] == "denominator"]
 
        if num_rows.empty or den_rows.empty:
            continue
 
        numerator_id   = num_rows.iloc[0]["source_variable_id"]
        denominator_id = den_rows.iloc[0]["source_variable_id"]
 
        num_code = variables_df[
            variables_df["variable_id"] == numerator_id
        ]["var_code"].iloc[0]
        den_code = variables_df[
            variables_df["variable_id"] == denominator_id
        ]["var_code"].iloc[0]
 
        # Source percentation bisa berasal dari hasil combine
        num_df = realisasi_df[realisasi_df["var_code"] == num_code].copy()
        den_df = realisasi_df[realisasi_df["var_code"] == den_code].copy()
 
        if num_df.empty or den_df.empty:
            print(f"  [WARN] Ratio {target_var_code}: "
                  f"source tidak ditemukan "
                  f"(num={num_code}: {'ada' if not num_df.empty else 'kosong'}, "
                  f"den={den_code}: {'ada' if not den_df.empty else 'kosong'})")
            continue
 
        ratio = num_df.merge(
            den_df, on="kdo_bsi", suffixes=("_num", "_den")
        )
 
        existing_cols = [c for c in calc_cols if c in num_df.columns]
        for col in existing_cols:
            num_col = f"{col}_num" if f"{col}_num" in ratio.columns else col
            den_col = f"{col}_den" if f"{col}_den" in ratio.columns else col
 
            num_val = pd.to_numeric(ratio[num_col], errors="coerce")
            den_val = pd.to_numeric(ratio[den_col], errors="coerce")
 
            if multiply_100:
                ratio[col] = np.where(
                    den_val == 0, np.nan, (num_val / den_val) * 100
                )
            else:
                ratio[col] = np.where(
                    den_val == 0, np.nan, num_val / den_val
                )
 
        result = ratio[["kdo_bsi"] + existing_cols].copy()
        result["var_code"] = target_var_code
        ratio_rows.append(result)
 
    if ratio_rows:
        df_ratio = pd.concat(ratio_rows, ignore_index=True)
        # Hapus variabel yang akan di-overwrite oleh hasil formula percentation
        target_codes = df_ratio["var_code"].unique()
        realisasi_df = realisasi_df[~realisasi_df["var_code"].isin(target_codes)]

        realisasi_df = pd.concat(
            [realisasi_df, df_ratio], ignore_index=True
        )
 
    realisasi_df = realisasi_df.sort_values(
        ["kdo_bsi", "var_code"]
    ).reset_index(drop=True)
 
    return realisasi_df 


# ====================================================================
# GROWTH
# ==================================================================== 

def calculate_growth(
    realisasi_df,
    configs_df,
    components_df,
    variables_df,
    period_cols,
    baseline_col,
):
    """
    Untuk setiap config bertipe 'growth':
        target_var[periode] = source_var[periode] - source_var[baseline_dec]

    Source bisa berupa:
    - Variabel raw dari import (misal TAB)
    - Hasil combine yang sudah ada di realisasi_df (misal PHE_CBR)

    Keduanya sudah tersedia karena calculate_combine() dijalankan lebih dulu
    dan hasilnya langsung masuk ke realisasi_df (incremental).
    """
    growth_rows = []
    growth_configs = configs_df[configs_df["formula_type"] == "growth"]

    for _, config in growth_configs.iterrows():

        config_id          = config["config_id"]
        target_variable_id = config["variable_id"]

        target_var_row = variables_df[
            variables_df["variable_id"] == target_variable_id
        ]
        if target_var_row.empty:
            continue
        target_var_code = target_var_row.iloc[0]["var_code"]

        components = components_df[components_df["config_id"] == config_id]
        subj_rows  = components[components["role"] == "subject"]

        if subj_rows.empty:
            print(f"  [WARN] Growth {target_var_code} (config {config_id}): "
                  f"tidak ada subject di formula_components")
            continue

        subject_id = subj_rows.iloc[0]["source_variable_id"]
        subject_code_row = variables_df[
            variables_df["variable_id"] == subject_id
        ]
        if subject_code_row.empty:
            continue
        subject_code = subject_code_row.iloc[0]["var_code"]

        # Source bisa raw atau hasil combine — keduanya sudah ada
        # di realisasi_df karena calculate_combine() sudah jalan
        temp = realisasi_df[
            realisasi_df["var_code"] == subject_code
        ].copy()

        if temp.empty:
            print(f"  [WARN] Growth {target_var_code}: "
                  f"tidak ada data untuk subject '{subject_code}'")
            continue

        if baseline_col not in temp.columns:
            print(f"  [WARN] Growth {target_var_code}: "
                  f"kolom baseline '{baseline_col}' tidak ada")
            continue

        existing_cols = [c for c in period_cols if c in temp.columns]
        all_num_cols  = existing_cols + [baseline_col]
        temp = _to_numeric_cols(temp, all_num_cols)

        baseline_series = temp[baseline_col].values
        for col in existing_cols:
            temp[col] = temp[col].values - baseline_series

        temp["var_code"] = target_var_code
        growth_rows.append(
            temp[["kdo_bsi", "var_code"] + existing_cols].copy()
        )

    if growth_rows:
        df_growth = pd.concat(growth_rows, ignore_index=True)
        # Hapus variabel yang akan di-overwrite oleh hasil formula growth
        target_codes = df_growth["var_code"].unique()
        realisasi_df = realisasi_df[~realisasi_df["var_code"].isin(target_codes)]

        realisasi_df = pd.concat(
            [realisasi_df, df_growth], ignore_index=True
        )

    realisasi_df = realisasi_df.sort_values(
        ["kdo_bsi", "var_code"]
    ).reset_index(drop=True)

    return realisasi_df