"""
calculation_service.py — Kalkulasi skor KPI per periode

Alur:
    load_data()
        → calculate_combine()   (butuh formula_components terisi)
        → calculate_ratio()     (butuh formula_components terisi)
        → calculate_growth()    (butuh formula_components terisi)
        → loop per (cabang × variabel) → achievement → score
        → save_variable_scores()   (UPSERT)
        → save_kpi_score_records() (UPSERT cabang + area)
"""

import pandas as pd
import numpy as np
from datetime import date

from db import get_engine, get_connection
from services.formula_services import (
    calculate_combine,
    calculate_ratio,
    calculate_growth,
)

FORMULA_TYPES = {"combine", "percentation", "growth"}


# ====================================================================
# LOAD DATA
# ====================================================================

def load_realisasi_wide(engine, periode: date, baseline_periode: date):
    periode_col  = str(periode)
    baseline_col = str(baseline_periode)

    current_df = pd.read_sql(
        """
        SELECT b.kdo_bsi, v.var_code, r.value AS val
        FROM   kpi_realizations r
        JOIN   branches         b ON r.branch_id   = b.branch_id
        JOIN   kpi_variables    v ON r.variable_id = v.variable_id
        WHERE  r.periode = %(p)s
        """,
        engine,
        params={"p": str(periode)},
    ).rename(columns={"val": periode_col})
    current_df = current_df.drop_duplicates(subset=["kdo_bsi", "var_code"], keep="last")

    baseline_df = pd.read_sql(
        """
        SELECT b.kdo_bsi, v.var_code, r.value AS val
        FROM   kpi_realizations r
        JOIN   branches         b ON r.branch_id   = b.branch_id
        JOIN   kpi_variables    v ON r.variable_id = v.variable_id
        WHERE  r.periode = %(p)s
        """,
        engine,
        params={"p": str(baseline_periode)},
    ).rename(columns={"val": baseline_col})
    baseline_df = baseline_df.drop_duplicates(subset=["kdo_bsi", "var_code"], keep="last")

    merged = current_df.merge(
        baseline_df[["kdo_bsi", "var_code", baseline_col]],
        on=["kdo_bsi", "var_code"],
        how="left",
    )

    return merged, periode_col, baseline_col


def load_configs(engine, periode: date):
    return pd.read_sql(
        """
        SELECT config_id, variable_id, periode, formula_type,
               is_displayed, max_weight
        FROM   variable_configs
        WHERE  periode = %(p)s
        """,
        engine,
        params={"p": str(periode)},
    )


def load_components(engine):
    return pd.read_sql("SELECT * FROM formula_components", engine)


def load_variables(engine):
    return pd.read_sql("SELECT * FROM kpi_variables", engine)


def load_targets(engine, periode: date):
    df = pd.read_sql(
        """
        SELECT b.kdo_bsi, v.var_code, t.target_value
        FROM   kpi_targets   t
        JOIN   branches      b ON t.branch_id   = b.branch_id
        JOIN   kpi_variables v ON t.variable_id = v.variable_id
        WHERE  t.periode = %(p)s
        """,
        engine,
        params={"p": str(periode)},
    )
    return df.drop_duplicates(subset=["kdo_bsi", "var_code"], keep="last")


def load_branches(engine):
    return pd.read_sql(
        """
        SELECT b.branch_id, b.kdo_bsi, b.area_id, b.condition_id, a.area_name
        FROM branches b
        LEFT JOIN areas a ON b.area_id = a.area_id
        """,
        engine,
    )


def load_weights(engine, periode: date):
    return pd.read_sql(
        """
        SELECT vcw.condition_id, vcw.config_id, vcw.weight
        FROM   variable_config_weights vcw
        JOIN   variable_configs        vc ON vc.config_id = vcw.config_id
        WHERE  vc.periode = %(p)s
        """,
        engine,
        params={"p": str(periode)},
    )


# ====================================================================
# ACHIEVEMENT & SCORE
# ====================================================================

def calculate_achievement(realization, target, var_type="POSITIVE"):
    if target is None or pd.isna(target) or target == 0:
        return 100.0
    if realization is None or pd.isna(realization):
        return 0.0
        
    if target < 0 or var_type == "NEGATIVE":
        if realization == 0:
            return 100.0
        return (target / realization) * 100
        
    if var_type == "POSITIVE":
        return (realization / target) * 100
        
    return 0.0


def calculate_score(achievement, weight, max_weight):
    if achievement is None or pd.isna(achievement) or weight is None:
        return 0.0
    cap = float(max_weight) if (max_weight is not None and not pd.isna(max_weight)) else 100.0
    capped = max(0.0, min(achievement, cap))
    return (capped / 100) * weight


# ====================================================================
# MAIN: CALCULATE PERIOD
# ====================================================================

def calculate_period(conn, periode):
    if isinstance(periode, str):
        periode = date.fromisoformat(periode)

    baseline_periode = date(periode.year - 1, 12, 1)

    print(f"[INFO] Periode: {periode}  |  Baseline: {baseline_periode}")

    engine = get_engine()

    # ── 1. Load Data ─────────────────────────────────────────────────
    realisasi_df, periode_col, baseline_col = load_realisasi_wide(
        engine, periode, baseline_periode
    )
    configs    = load_configs(engine, periode)
    components = load_components(engine)
    variables  = load_variables(engine)
    targets    = load_targets(engine, periode)
    branches   = load_branches(engine)
    weights_df = load_weights(engine, periode)

    if realisasi_df.empty:
        print(f"[SKIP] Tidak ada realisasi untuk periode {periode}")
        return None
    if configs.empty:
        print(f"[SKIP] Tidak ada variable_configs untuk periode {periode}")
        return None

    print(f"[INFO] {len(realisasi_df)} realisasi | {len(configs)} configs | "
          f"{len(branches)} cabang | {len(components)} components")

    period_cols = [periode_col]

    # ── 2. Jalankan Formula ──────────────────────────────────────────
    realisasi_df = calculate_combine(
        realisasi_df, configs, components, variables,
        period_cols, baseline_col=baseline_col,
    )
    realisasi_df = calculate_ratio(
        realisasi_df, configs, components, variables,
        period_cols, baseline_col=baseline_col,
    )
    realisasi_df = calculate_growth(
        realisasi_df, configs, components, variables,
        period_cols, baseline_col,
    )

    # ── 3. Hitung Score ──────────────────────────────────────────────
    # FIX: tidak lagi memisah formula_configs vs direct_configs.
    #
    # Pemisahan lama menggunakan:
    #   formula_configs = configs[configs["formula_type"].isin(FORMULA_TYPES)]
    #   direct_configs  = configs[~configs["formula_type"].isin(FORMULA_TYPES)]
    #
    # Bug: pandas .isin() mengembalikan False untuk NaN/None, dan ~False = True,
    # sehingga baris dengan formula_type=NULL masuk ke direct_configs. Tapi
    # karena closure _score_configs di-call dua kali dan all_scores di-append
    # keduanya, config yang formula_type-nya tidak terduga bisa diproses dua
    # kali → baris duplikat di all_scores → total_score double.
    #
    # Solusi: loop satu kali saja. formula_type_used diisi jika nilainya
    # termasuk FORMULA_TYPES, None jika tidak (direct/raw).

    all_scores = []

    for _, config in configs.iterrows():
        config_id         = config["config_id"]
        variable_id       = config["variable_id"]
        is_displayed      = bool(config["is_displayed"])
        formula_type      = config["formula_type"]
        max_weight        = config["max_weight"]

        # formula_type_used: hanya isi jika termasuk enum yang valid
        formula_type_used = (
            formula_type
            if (isinstance(formula_type, str) and formula_type in FORMULA_TYPES)
            else None
        )

        var_row = variables[variables["variable_id"] == variable_id]
        if var_row.empty:
            continue

        var_code = var_row.iloc[0]["var_code"]
        var_type = var_row.iloc[0]["type"]

        result_df = realisasi_df[
            realisasi_df["var_code"] == var_code
        ][["kdo_bsi", periode_col]].copy()

        if result_df.empty:
            print(f"  [WARN] Tidak ada data realisasi untuk {var_code}")
            continue

        result_df["realization_used"] = pd.to_numeric(
            result_df[periode_col], errors="coerce"
        )

        tgt = targets[targets["var_code"] == var_code][
            ["kdo_bsi", "target_value"]
        ]
        result_df = result_df.merge(tgt, on="kdo_bsi", how="left")
        result_df["target_used"] = pd.to_numeric(
            result_df["target_value"], errors="coerce"
        )

        result_df = result_df.merge(
            branches[["kdo_bsi", "branch_id", "condition_id"]],
            on="kdo_bsi",
            how="left",
        )

        w_map = weights_df[weights_df["config_id"] == config_id][
            ["condition_id", "weight"]
        ]
        result_df = result_df.merge(w_map, on="condition_id", how="left")
        result_df["weight_used"] = result_df["weight"].fillna(0)

        result_df["pencapaian"] = result_df.apply(
            lambda r: calculate_achievement(
                r["realization_used"], r["target_used"], var_type
            ),
            axis=1,
        )
        result_df["score"] = result_df.apply(
            lambda r, mw=max_weight: calculate_score(
                r["pencapaian"], r["weight_used"], mw
            ),
            axis=1,
        )

        result_df["variable_id"]       = variable_id
        result_df["formula_type_used"] = formula_type_used
        result_df["periode"]           = periode
        result_df["is_displayed"]      = is_displayed

        all_scores.append(
            result_df[[
                "branch_id", "variable_id", "periode",
                "realization_used", "target_used", "pencapaian",
                "weight_used", "score", "formula_type_used",
                "is_displayed",
            ]]
        )

    if not all_scores:
        print("[SKIP] Tidak ada skor yang dihasilkan")
        return None

    final_scores = pd.concat(all_scores, ignore_index=True)
    final_scores = final_scores[final_scores["branch_id"].notna()].copy()
    final_scores["branch_id"] = final_scores["branch_id"].astype(int)

    # ── 3.5 Agregasi Skor Area ──────────────────────────────────────────
    # Pisahkan cabang asli dan cabang dummy Area (condition_id = 9)
    # Exclude juga Regional (condition_id = 10) dari cabang asli
    actual_branches = branches[~branches["condition_id"].isin([9, 10])]
    dummy_branches = branches[branches["condition_id"] == 9]

    # ── A) Build Area-level realisasi dari realisasi_df ─────────────
    # Gabungkan realisasi cabang asli dengan area_id, lalu SUM per area × var_code
    branch_area_map = actual_branches[["kdo_bsi", "area_id"]].drop_duplicates()
    area_real = realisasi_df.merge(branch_area_map, on="kdo_bsi", how="inner")

    val_cols = [periode_col]
    if baseline_col and baseline_col in area_real.columns:
        val_cols.append(baseline_col)
    for c in val_cols:
        area_real[c] = pd.to_numeric(area_real[c], errors="coerce")

    area_real_agg = (
        area_real.groupby(["area_id", "var_code"])[val_cols]
        .sum(min_count=1)
        .reset_index()
    )

    # ── B) Override dengan data realisasi milik Area dummy branch ───
    # Jika Area punya data sendiri di kpi_realizations (misalnya JUMLAH_SALES),
    # gunakan nilai tersebut menggantikan hasil SUM dari cabang.
    dummy_kdo_map = dummy_branches[["kdo_bsi", "area_id"]].drop_duplicates()
    for _, dm in dummy_kdo_map.iterrows():
        own_data = realisasi_df[realisasi_df["kdo_bsi"] == dm["kdo_bsi"]].copy()
        if own_data.empty:
            continue
        for c in val_cols:
            if c in own_data.columns:
                own_data[c] = pd.to_numeric(own_data[c], errors="coerce")
        for _, row in own_data.iterrows():
            vc = row["var_code"]
            mask = (
                (area_real_agg["area_id"] == dm["area_id"])
                & (area_real_agg["var_code"] == vc)
            )
            if mask.any():
                for c in val_cols:
                    if c in own_data.columns:
                        area_real_agg.loc[mask, c] = row[c]
            else:
                new_row = {"area_id": dm["area_id"], "var_code": vc}
                for c in val_cols:
                    new_row[c] = row.get(c, np.nan)
                area_real_agg = pd.concat(
                    [area_real_agg, pd.DataFrame([new_row])], ignore_index=True
                )

    # ── C) Recalculate percentation formulas di level Area ──────────
    # Untuk variabel rasio (PRODSALES=PHE/JUMLAH_SALES, KOL2%, NPF%),
    # tidak bisa pakai SUM dari cabang. Hitung ulang dari source Area.
    perc_configs = configs[configs["formula_type"] == "percentation"]
    perc_target_vcs = set()

    for _, cfg in perc_configs.iterrows():
        config_id = cfg["config_id"]
        var_id = cfg["variable_id"]
        vr = variables[variables["variable_id"] == var_id]
        if vr.empty:
            continue
        target_vc = vr.iloc[0]["var_code"]
        target_unit = vr.iloc[0].get("unit", None)
        mul100 = (str(target_unit).strip() == "%")

        comps = components[components["config_id"] == config_id]
        nr = comps[comps["role"] == "numerator"]
        dr = comps[comps["role"] == "denominator"]
        if nr.empty or dr.empty:
            continue

        num_vc = variables[
            variables["variable_id"] == nr.iloc[0]["source_variable_id"]
        ]["var_code"].iloc[0]
        den_vc = variables[
            variables["variable_id"] == dr.iloc[0]["source_variable_id"]
        ]["var_code"].iloc[0]

        for aid in area_real_agg["area_id"].unique():
            num_row = area_real_agg[
                (area_real_agg["area_id"] == aid)
                & (area_real_agg["var_code"] == num_vc)
            ]
            den_row = area_real_agg[
                (area_real_agg["area_id"] == aid)
                & (area_real_agg["var_code"] == den_vc)
            ]
            if num_row.empty or den_row.empty:
                continue

            new_vals = {}
            for c in val_cols:
                nv = num_row.iloc[0][c]
                dv = den_row.iloc[0][c]
                if pd.notna(dv) and dv != 0:
                    new_vals[c] = (nv / dv * 100) if mul100 else (nv / dv)
                else:
                    new_vals[c] = np.nan

            mask = (
                (area_real_agg["area_id"] == aid)
                & (area_real_agg["var_code"] == target_vc)
            )
            if mask.any():
                for c in val_cols:
                    area_real_agg.loc[mask, c] = new_vals[c]
            else:
                new_row = {"area_id": aid, "var_code": target_vc}
                new_row.update(new_vals)
                area_real_agg = pd.concat(
                    [area_real_agg, pd.DataFrame([new_row])], ignore_index=True
                )

        perc_target_vcs.add(target_vc)

    # ── D) Recalculate growth yang subject-nya adalah percentation ──
    # Growth lain (subject direct/combine) sudah benar pakai SUM.
    growth_configs = configs[configs["formula_type"] == "growth"]
    for _, cfg in growth_configs.iterrows():
        config_id = cfg["config_id"]
        var_id = cfg["variable_id"]
        vr = variables[variables["variable_id"] == var_id]
        if vr.empty:
            continue
        target_vc = vr.iloc[0]["var_code"]

        comps = components[components["config_id"] == config_id]
        sr = comps[comps["role"] == "subject"]
        if sr.empty:
            continue

        subj_id = sr.iloc[0]["source_variable_id"]
        subj_row_df = variables[variables["variable_id"] == subj_id]
        if subj_row_df.empty:
            continue
        subj_vc = subj_row_df.iloc[0]["var_code"]

        # Hanya recalculate jika subject adalah hasil percentation
        if subj_vc not in perc_target_vcs:
            continue

        if len(val_cols) < 2 or baseline_col not in val_cols:
            continue

        for aid in area_real_agg["area_id"].unique():
            s_row = area_real_agg[
                (area_real_agg["area_id"] == aid)
                & (area_real_agg["var_code"] == subj_vc)
            ]
            if s_row.empty:
                continue

            current_val = s_row.iloc[0][periode_col]
            baseline_val = s_row.iloc[0][baseline_col]

            if pd.notna(current_val) and pd.notna(baseline_val):
                growth_val = current_val - baseline_val
            else:
                growth_val = np.nan

            mask = (
                (area_real_agg["area_id"] == aid)
                & (area_real_agg["var_code"] == target_vc)
            )
            if mask.any():
                area_real_agg.loc[mask, periode_col] = growth_val
            else:
                new_row = {
                    "area_id": aid,
                    "var_code": target_vc,
                    periode_col: growth_val,
                }
                area_real_agg = pd.concat(
                    [area_real_agg, pd.DataFrame([new_row])], ignore_index=True
                )

    # ── E) Build targets di level Area (aggregated + override) ────────
    # Langkah 1: Aggregate target dari cabang asli (SUM)
    branch_targets_df = targets.merge(branch_area_map, on="kdo_bsi", how="inner")
    area_target_agg = (
        branch_targets_df.groupby(["area_id", "var_code"])["target_value"]
        .sum()
        .reset_index()
    )

    # Langkah 2: Override dengan target milik Area dummy branch (dari DB import user)
    dummy_kdo_to_area = dict(
        zip(dummy_branches["kdo_bsi"], dummy_branches["area_id"])
    )
    for kdo, aid in dummy_kdo_to_area.items():
        own_targets = targets[targets["kdo_bsi"] == kdo]
        if own_targets.empty:
            continue
        for _, row in own_targets.iterrows():
            vc = row["var_code"]
            val = pd.to_numeric(row["target_value"], errors="coerce")
            mask = (
                (area_target_agg["area_id"] == aid)
                & (area_target_agg["var_code"] == vc)
            )
            if mask.any():
                area_target_agg.loc[mask, "target_value"] = val
            else:
                area_target_agg = pd.concat(
                    [area_target_agg, pd.DataFrame([{
                        "area_id": aid,
                        "var_code": vc,
                        "target_value": val,
                    }])],
                    ignore_index=True,
                )

    # ── E.2) SPECIAL RULE: SME_MIKRO_GROWTH_YTD (Level Area) ────────
    # Penjumlahan realisasi dan target dari SME_GROWTH_YTD + MIKRO_GROWTH_YTD
    for aid in dummy_branches["area_id"].unique():
        # 1. Realisasi Gabungan
        r_sme = area_real_agg[(area_real_agg["area_id"] == aid) & (area_real_agg["var_code"] == "SME_GROWTH_YTD")]
        r_mikro = area_real_agg[(area_real_agg["area_id"] == aid) & (area_real_agg["var_code"] == "MIKRO_GROWTH_YTD")]
        v_sme = pd.to_numeric(r_sme.iloc[0].get(periode_col, 0.0), errors="coerce") if not r_sme.empty else 0.0
        v_mikro = pd.to_numeric(r_mikro.iloc[0].get(periode_col, 0.0), errors="coerce") if not r_mikro.empty else 0.0
        sm_real = (v_sme if pd.notna(v_sme) else 0.0) + (v_mikro if pd.notna(v_mikro) else 0.0)

        mask_r = (area_real_agg["area_id"] == aid) & (area_real_agg["var_code"] == "SME_MIKRO_GROWTH_YTD")
        if mask_r.any():
            area_real_agg.loc[mask_r, periode_col] = sm_real
        else:
            area_real_agg = pd.concat([area_real_agg, pd.DataFrame([{
                "area_id": aid,
                "var_code": "SME_MIKRO_GROWTH_YTD",
                periode_col: sm_real
            }])], ignore_index=True)

        # 2. Target Gabungan
        t_sme = area_target_agg[(area_target_agg["area_id"] == aid) & (area_target_agg["var_code"] == "SME_GROWTH_YTD")]
        t_mikro = area_target_agg[(area_target_agg["area_id"] == aid) & (area_target_agg["var_code"] == "MIKRO_GROWTH_YTD")]
        tv_sme = pd.to_numeric(t_sme.iloc[0]["target_value"], errors="coerce") if not t_sme.empty else 0.0
        tv_mikro = pd.to_numeric(t_mikro.iloc[0]["target_value"], errors="coerce") if not t_mikro.empty else 0.0
        sm_target = (tv_sme if pd.notna(tv_sme) else 0.0) + (tv_mikro if pd.notna(tv_mikro) else 0.0)

        mask_t = (area_target_agg["area_id"] == aid) & (area_target_agg["var_code"] == "SME_MIKRO_GROWTH_YTD")
        if mask_t.any():
            area_target_agg.loc[mask_t, "target_value"] = sm_target
        else:
            area_target_agg = pd.concat([area_target_agg, pd.DataFrame([{
                "area_id": aid,
                "var_code": "SME_MIKRO_GROWTH_YTD",
                "target_value": sm_target
            }])], ignore_index=True)


    # ── F) Build area_final_scores ──────────────────────────────────
    area_weights = weights_df[weights_df["condition_id"] == 9].copy()
    area_weights = area_weights.merge(
        configs[["config_id", "variable_id", "max_weight"]],
        on="config_id",
        how="left",
    )

    area_scores_list = []
    for _, cfg in configs.iterrows():
        var_id = cfg["variable_id"]
        is_displayed = bool(cfg["is_displayed"])
        formula_type = cfg["formula_type"]
        max_weight = cfg["max_weight"]
        formula_type_used = (
            formula_type
            if (isinstance(formula_type, str) and formula_type in FORMULA_TYPES)
            else None
        )

        vr = variables[variables["variable_id"] == var_id]
        if vr.empty:
            continue
        vc = vr.iloc[0]["var_code"]
        var_type = vr.iloc[0]["type"]

        # Weight untuk Area (condition_id = 9)
        w_row = area_weights[area_weights["variable_id"] == var_id]
        weight = float(w_row.iloc[0]["weight"]) if not w_row.empty else 0.0

        for _, dm in dummy_branches.iterrows():
            aid = dm["area_id"]
            bid = dm["branch_id"]

            # Realisasi dari area_real_agg
            r_row = area_real_agg[
                (area_real_agg["area_id"] == aid)
                & (area_real_agg["var_code"] == vc)
            ]
            if r_row.empty:
                continue
            realization = r_row.iloc[0].get(periode_col, np.nan)
            if pd.isna(realization):
                realization = 0.0

            # Target dari area_target_agg (sudah aggregated + override)
            t_row = area_target_agg[
                (area_target_agg["area_id"] == aid)
                & (area_target_agg["var_code"] == vc)
            ]
            target = (
                pd.to_numeric(t_row.iloc[0]["target_value"], errors="coerce")
                if not t_row.empty
                else 0.0
            )
            if pd.isna(target):
                target = 0.0

            pencapaian = calculate_achievement(realization, target, var_type)
            score = calculate_score(pencapaian, weight, max_weight)

            area_scores_list.append({
                "branch_id": bid,
                "variable_id": var_id,
                "periode": periode,
                "realization_used": realization,
                "target_used": target,
                "pencapaian": pencapaian,
                "weight_used": weight,
                "score": score,
                "formula_type_used": formula_type_used,
                "is_displayed": is_displayed,
            })

    area_final_scores = pd.DataFrame(area_scores_list)
    if not area_final_scores.empty:
        area_final_scores = area_final_scores[[
            "branch_id", "variable_id", "periode",
            "realization_used", "target_used", "pencapaian",
            "weight_used", "score", "formula_type_used", "is_displayed"
        ]].copy()

    # Hapus data branch_id dummy yang mungkin sudah masuk dari proses perhitungan cabang
    final_scores = final_scores[~final_scores["branch_id"].isin(dummy_branches["branch_id"])]
    # Gabungkan kembali hasil perhitungan Area ke final_scores
    final_scores = pd.concat([final_scores, area_final_scores], ignore_index=True)
    final_scores["branch_id"] = final_scores["branch_id"].astype(int)

    # ── 3.6 Agregasi Skor Regional ──────────────────────────────────────
    reg_dummy_branches = branches[branches["condition_id"] == 10]
    if not reg_dummy_branches.empty:
        # A) Build Regional-level realisasi
        reg_real_agg = (
            area_real_agg.groupby("var_code")[val_cols]
            .sum(min_count=1)
            .reset_index()
        )
        
        # Override data Regional dari kpi_realizations (jika ada)
        reg_kdo_map = reg_dummy_branches[["kdo_bsi", "branch_id"]].drop_duplicates()
        reg_own_realizations = realisasi_df[realisasi_df["kdo_bsi"].isin(reg_kdo_map["kdo_bsi"])]
        
        for r_kdo, b_id in zip(reg_kdo_map["kdo_bsi"], reg_kdo_map["branch_id"]):
            own_real = reg_own_realizations[reg_own_realizations["kdo_bsi"] == r_kdo]
            for _, row in own_real.iterrows():
                vc = row["var_code"]
                val = pd.to_numeric(row[periode_col], errors="coerce")
                mask = (reg_real_agg["var_code"] == vc)
                if mask.any():
                    reg_real_agg.loc[mask, periode_col] = val
                else:
                    reg_real_agg = pd.concat([reg_real_agg, pd.DataFrame([{"var_code": vc, periode_col: val}])], ignore_index=True)
                
                if baseline_col and baseline_col in row:
                    base_val = pd.to_numeric(row[baseline_col], errors="coerce")
                    reg_real_agg.loc[reg_real_agg["var_code"] == vc, baseline_col] = base_val
        


        # E) Build Regional-level target
        reg_target_agg = (
            area_target_agg.groupby("var_code")["target_value"]
            .sum()
            .reset_index()
        )
        
        # Override target Regional
        for r_kdo, b_id in zip(reg_kdo_map["kdo_bsi"], reg_kdo_map["branch_id"]):
            own_targets = targets[targets["kdo_bsi"] == r_kdo]
            for _, row in own_targets.iterrows():
                vc = row["var_code"]
                val = pd.to_numeric(row["target_value"], errors="coerce")
                mask = (reg_target_agg["var_code"] == vc)
                if mask.any():
                    reg_target_agg.loc[mask, "target_value"] = val
                else:
                    reg_target_agg = pd.concat([reg_target_agg, pd.DataFrame([{"var_code": vc, "target_value": val}])], ignore_index=True)

        # E.2) SPECIAL RULE: SME_MIKRO_GROWTH_YTD (Level Regional)
        r_sme = reg_real_agg[reg_real_agg["var_code"] == "SME_GROWTH_YTD"]
        r_mikro = reg_real_agg[reg_real_agg["var_code"] == "MIKRO_GROWTH_YTD"]
        v_sme = pd.to_numeric(r_sme.iloc[0].get(periode_col, 0.0), errors="coerce") if not r_sme.empty else 0.0
        v_mikro = pd.to_numeric(r_mikro.iloc[0].get(periode_col, 0.0), errors="coerce") if not r_mikro.empty else 0.0
        sm_real = (v_sme if pd.notna(v_sme) else 0.0) + (v_mikro if pd.notna(v_mikro) else 0.0)
        mask_r = (reg_real_agg["var_code"] == "SME_MIKRO_GROWTH_YTD")
        if mask_r.any():
            reg_real_agg.loc[mask_r, periode_col] = sm_real
        else:
            reg_real_agg = pd.concat([reg_real_agg, pd.DataFrame([{"var_code": "SME_MIKRO_GROWTH_YTD", periode_col: sm_real}])], ignore_index=True)

        t_sme = reg_target_agg[reg_target_agg["var_code"] == "SME_GROWTH_YTD"]
        t_mikro = reg_target_agg[reg_target_agg["var_code"] == "MIKRO_GROWTH_YTD"]
        tv_sme = pd.to_numeric(t_sme.iloc[0]["target_value"], errors="coerce") if not t_sme.empty else 0.0
        tv_mikro = pd.to_numeric(t_mikro.iloc[0]["target_value"], errors="coerce") if not t_mikro.empty else 0.0
        sm_target = (tv_sme if pd.notna(tv_sme) else 0.0) + (tv_mikro if pd.notna(tv_mikro) else 0.0)
        mask_t = (reg_target_agg["var_code"] == "SME_MIKRO_GROWTH_YTD")
        if mask_t.any():
            reg_target_agg.loc[mask_t, "target_value"] = sm_target
        else:
            reg_target_agg = pd.concat([reg_target_agg, pd.DataFrame([{"var_code": "SME_MIKRO_GROWTH_YTD", "target_value": sm_target}])], ignore_index=True)

        # F) Build reg_final_scores
        reg_weights = weights_df[weights_df["condition_id"] == 10].copy()
        reg_weights = reg_weights.merge(
            configs[["config_id", "variable_id", "max_weight"]],
            on="config_id",
            how="left",
        )

        reg_scores_list = []
        for _, cfg in configs.iterrows():
            var_id = cfg["variable_id"]
            is_displayed = bool(cfg["is_displayed"])
            formula_type = cfg["formula_type"]
            max_weight = cfg["max_weight"]
            formula_type_used = (
                formula_type if (isinstance(formula_type, str) and formula_type in FORMULA_TYPES) else None
            )

            vr = variables[variables["variable_id"] == var_id]
            if vr.empty: continue
            vc = vr.iloc[0]["var_code"]
            var_type = vr.iloc[0]["type"]

            w_row = reg_weights[reg_weights["variable_id"] == var_id]
            weight = float(w_row.iloc[0]["weight"]) if not w_row.empty else 0.0

            for _, dm in reg_dummy_branches.iterrows():
                bid = dm["branch_id"]

                r_row = reg_real_agg[reg_real_agg["var_code"] == vc]
                if r_row.empty: continue
                realization = r_row.iloc[0].get(periode_col, np.nan)
                if pd.isna(realization): realization = 0.0

                t_row = reg_target_agg[reg_target_agg["var_code"] == vc]
                target = pd.to_numeric(t_row.iloc[0]["target_value"], errors="coerce") if not t_row.empty else 0.0
                if pd.isna(target): target = 0.0

                pencapaian = calculate_achievement(realization, target, var_type)
                score = calculate_score(pencapaian, weight, max_weight)

                reg_scores_list.append({
                    "branch_id": bid,
                    "variable_id": var_id,
                    "periode": periode,
                    "realization_used": realization,
                    "target_used": target,
                    "pencapaian": pencapaian,
                    "weight_used": weight,
                    "score": score,
                    "formula_type_used": formula_type_used,
                    "is_displayed": is_displayed,
                })

        reg_final_scores = pd.DataFrame(reg_scores_list)
        if not reg_final_scores.empty:
            final_scores = final_scores[~final_scores["branch_id"].isin(reg_dummy_branches["branch_id"])]
            final_scores = pd.concat([final_scores, reg_final_scores], ignore_index=True)
            final_scores["branch_id"] = final_scores["branch_id"].astype(int)
    # ─────────────────────────────────────────────────────────────────


    print(f"[INFO] Total skor: {len(final_scores)} baris | "
          f"is_displayed=True: {final_scores['is_displayed'].sum()} baris")

    # ── DEBUG: tampilkan rincian skor satu cabang sebelum disimpan ──────
    # sample_branch_id = int(final_scores["branch_id"].iloc[2])
    # sample_branch    = final_scores[final_scores["branch_id"] == sample_branch_id].copy()

    # displayed   = sample_branch[sample_branch["is_displayed"] == True]
    # undisplayed = sample_branch[sample_branch["is_displayed"] == False]

    # Lookup var_code untuk branch_id sample (join ke variables via variable_id)
    # var_lookup = variables.set_index("variable_id")["var_code"].to_dict()
    # displayed_debug = displayed.copy()
    # displayed_debug["var_code"] = displayed_debug["variable_id"].map(var_lookup)

    # print(f"\n{'='*60}")
    # print(f"[DEBUG] Sample branch_id : {sample_branch_id}")
    # print(f"[DEBUG] Total variabel   : {len(sample_branch)} "
    #       f"(is_displayed=True: {len(displayed)}, False: {len(undisplayed)})")
    # print(f"\n[DEBUG] Variabel yang MASUK ke kpi_score_records (is_displayed=True):")
    # print(
    #     displayed_debug[["var_code", "variable_id", "pencapaian", "weight_used", "score"]]
    #     .sort_values("var_code")
    #     .to_string(index=False)
    # )
    # print(f"\n[DEBUG] total_score cabang ini : "
    #       f"{displayed['score'].sum():.6f}")
    # if len(undisplayed) > 0:
    #     undisplayed_debug = undisplayed.copy()
    #     undisplayed_debug["var_code"] = undisplayed_debug["variable_id"].map(var_lookup)
    #     print(f"\n[DEBUG] Variabel yang TIDAK masuk (is_displayed=False):")
    #     print(
    #         undisplayed_debug[["var_code", "variable_id", "score"]]
    #         .sort_values("var_code")
    #         .to_string(index=False)
    #     )
    # print(f"{'='*60}\n")
    # ── END DEBUG ────────────────────────────────────────────────────

    # ── DEBUG AREA BALIKPAPAN ─────────────────────────────────────────
    # try:
    #     # Get dummy branch_id for Balikpapan Area
    #     balikpapan_mask = dummy_branches['area_name'].str.contains("Balikpapan", case=False, na=False)
    #     if balikpapan_mask.any():
    #         b_branch_id = dummy_branches[balikpapan_mask].iloc[0]['branch_id']
    #         b_area_id = dummy_branches[balikpapan_mask].iloc[0]['area_id']
            
    #         b_scores = area_final_scores[area_final_scores['branch_id'] == b_branch_id].copy()
            
    #         # Merge with variables to get var_code
    #         b_scores = b_scores.merge(variables[['variable_id', 'var_code']], on='variable_id', how='left')
            
    #         # Just focus on displayed variables for this debug
    #         b_scores_disp = b_scores
            
    #         print(f"\n{'='*60}")
    #         print(f"[DEBUG AREA BALIKPAPAN] Area ID: {b_area_id} | Dummy Branch ID: {b_branch_id}")
    #         print(f"[DEBUG AREA BALIKPAPAN] Aggregate Realisasi, Target, Pencapaian & Score (Sum of Branches):")
    #         print(
    #             b_scores_disp[['var_code', 'realization_used', 'target_used', 'pencapaian', 'weight_used', 'score']]
    #             .sort_values('var_code')
    #             .to_string(index=False)
    #         )
    #         print(f"[DEBUG AREA BALIKPAPAN] Total Score: {b_scores_disp['score'].sum():.6f}")
    #         print(f"{'='*60}\n")
    #     else:
    #         print("[DEBUG AREA BALIKPAPAN] Area Balikpapan not found in dummy branches.")
    # except Exception as e:
    #     print(f"[DEBUG AREA BALIKPAPAN] Error during debug: {e}")
    # ── END DEBUG AREA BALIKPAPAN ─────────────────────────────────────

    # ── 4. Simpan ke DB ──────────────────────────────────────────────
    n_scores  = save_variable_scores(conn, final_scores)
    n_records = save_kpi_score_records(conn, final_scores, branches, periode)
    conn.commit()

    print(f"[OK] {n_scores} variable_scores | {n_records} kpi_score_records")

    return {"variable_scores": n_scores, "score_records": n_records}


# ====================================================================
# SIMPAN KE DB
# ====================================================================

def save_variable_scores(conn, final_scores: pd.DataFrame) -> int:
    """
    UPSERT semua variable_scores — termasuk variabel is_displayed=False
    agar data audit tetap lengkap.
    """
    sql = """
        INSERT INTO variable_scores
            (branch_id, variable_id, periode,
             realization_used, target_used, pencapaian,
             weight_used, score, formula_type_used)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            realization_used  = VALUES(realization_used),
            target_used       = VALUES(target_used),
            pencapaian        = VALUES(pencapaian),
            weight_used       = VALUES(weight_used),
            score             = VALUES(score),
            formula_type_used = VALUES(formula_type_used)
    """

    def _f(v):
        return float(v) if pd.notna(v) else None

    valid_types = {"combine", "percentation", "growth"}

    data = [
        (
            int(r.branch_id),
            int(r.variable_id),
            str(r.periode),
            _f(r.realization_used),
            _f(r.target_used),
            _f(r.pencapaian),
            _f(r.weight_used),
            _f(r.score),
            r.formula_type_used if r.formula_type_used in valid_types else None,
        )
        for r in final_scores.itertuples(index=False)
    ]

    with conn.cursor() as cur:
        cur.executemany(sql, data)

    return len(data)


def save_kpi_score_records(
    conn,
    final_scores: pd.DataFrame,
    branches: pd.DataFrame,
    periode: date,
) -> int:
    """
    Hitung total_score per cabang dan per area.
    Hanya variabel dengan is_displayed=True yang dijumlahkan.
    """
    sql_upsert = """
        INSERT INTO kpi_score_records (entity_id, entity_type, periode, total_score)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE total_score = VALUES(total_score)
    """

    displayed_scores = final_scores[final_scores["is_displayed"] == True].copy()

    if displayed_scores.empty:
        print("[WARN] Tidak ada skor dengan is_displayed=True")
        return 0

    actual_branches = branches[~branches["condition_id"].isin([9, 10])]
    dummy_branches = branches[branches["condition_id"] == 9]

    # ── Per Cabang ───────────────────────────────────────────────────
    branch_scores = displayed_scores[displayed_scores["branch_id"].isin(actual_branches["branch_id"])]
    branch_totals = (
        branch_scores
        .groupby("branch_id")["score"]
        .sum()
        .reset_index()
        .rename(columns={"score": "total_score"})
    )

    branch_data = [
        (int(r.branch_id), "branch", str(periode), float(r.total_score))
        for r in branch_totals.itertuples(index=False)
    ]
    with conn.cursor() as cur:
        cur.executemany(sql_upsert, branch_data)

    # ── Per Area ─────────────────────────────────────────────────────
    # Jumlahkan score dari variabel-variabel Area yang tersimpan di dummy_branches
    area_scores_df = displayed_scores[displayed_scores["branch_id"].isin(dummy_branches["branch_id"])]
    
    area_totals = (
        area_scores_df
        .groupby("branch_id")["score"]
        .sum()
        .reset_index()
        .rename(columns={"score": "total_score"})
    )
    
    area_data = [
        (int(r.branch_id), "area", str(periode), float(r.total_score))
        for r in area_totals.itertuples(index=False)
    ]
    
    with conn.cursor() as cur:
        cur.executemany(sql_upsert, area_data)

    # ── Per Regional ─────────────────────────────────────────────────
    reg_dummy_branches = branches[branches["condition_id"] == 10]
    reg_scores_df = displayed_scores[displayed_scores["branch_id"].isin(reg_dummy_branches["branch_id"])]
    
    reg_totals = (
        reg_scores_df
        .groupby("branch_id")["score"]
        .sum()
        .reset_index()
        .rename(columns={"score": "total_score"})
    )
    
    reg_data = [
        (int(r.branch_id), "regional", str(periode), float(r.total_score))
        for r in reg_totals.itertuples(index=False)
    ]
    
    with conn.cursor() as cur:
        cur.executemany(sql_upsert, reg_data)

    return len(branch_data) + len(area_data) + len(reg_data)
