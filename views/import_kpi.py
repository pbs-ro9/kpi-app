import streamlit as st
import pandas as pd
import pymysql
import io
from datetime import datetime, date
from services.calculation_service import calculate_period

# ==============================================================================
# PAGE CONFIG
# ==============================================================================
def show_import():

    # st.set_page_config(
    #     layout="wide",
    #     page_title="Import Data KPI",
    #     page_icon="📥"
    # )

    # ==============================================================================
    # DATABASE CONFIG
    # ==============================================================================
    DB_CONFIG = {
        "host": st.secrets["mysql"]["host"],
        "user": st.secrets["mysql"]["user"],
        "password": st.secrets["mysql"]["password"],
        "database": st.secrets["mysql"]["database"],
        "port": st.secrets["mysql"]["port"],
        "charset": st.secrets["mysql"]["charset"]
    }

    # ==============================================================================
    # SIMPLE CSS
    # ==============================================================================
    st.markdown("""
    <style>
    .main .block-container{
        padding-top:2rem;
        padding-left:2rem;
        padding-right:2rem;
    }

    .card{
        background:white;
        padding:24px;
        border-radius:14px;
        border:1px solid #eaeaea;
        margin-bottom:20px;
    }

    .metric{
        background:#f8f9fb;
        padding:18px;
        border-radius:12px;
        text-align:center;
        border:1px solid #ececec;
    }

    .metric-number{
        font-size:32px;
        font-weight:700;
    }

    .metric-label{
        font-size:13px;
        color:#666;
    }

    .success-box{
        padding:16px;
        border-radius:12px;
        background:#f6ffed;
        border:1px solid #b7eb8f;
        color:#389e0d;
    }

    .error-box{
        padding:16px;
        border-radius:12px;
        background:#fff2f0;
        border:1px solid #ffccc7;
        color:#cf1322;
    }

    .warning-box{
        padding:16px;
        border-radius:12px;
        background:#fffbe6;
        border:1px solid #ffe58f;
        color:#d48806;
    }

   .back-link {
        display: inline-flex; align-items: center; gap: 6px;
        font-size: 13px; font-weight: 500; color: var(--text-muted);
        text-decoration: none; margin-bottom: 20px; transition: color 0.2s;
    }
    
    .back-link:hover { color: var(--accent); }
    </style>
    """, unsafe_allow_html=True)

    # ==============================================================================
    # DB HELPERS
    # ==============================================================================
    st.markdown('<a class="back-link" href="/" target="_self">← Kembali ke Dashboard</a>', unsafe_allow_html=True)
    
    def get_connection():
        return pymysql.connect(
            **DB_CONFIG,
            cursorclass=pymysql.cursors.DictCursor
        )    

    def load_lookup_data(conn):
        with conn.cursor() as cur:

            cur.execute("""
                SELECT branch_id, kdo_bsi
                FROM branches
            """)
            branches = {
                r["kdo_bsi"].strip().upper(): r["branch_id"]
                for r in cur.fetchall()
            }

            cur.execute("""
                SELECT variable_id, var_code
                FROM kpi_variables
            """)
            variables = {
                r["var_code"].strip().upper(): r["variable_id"]
                for r in cur.fetchall()
            }

        return branches, variables

    # ==============================================================================
    # PARSE PERIODE
    # ==============================================================================
    def parse_periode(raw):

        if pd.isna(raw):
            return None

        s = str(raw).strip()

        formats = [
            "%Y-%m-%d",
            "%Y-%m",
            "%m/%Y",
            "%Y/%m",
            "%m-%Y"
        ]

        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).replace(day=1).date()
            except:
                pass

        try:
            return pd.to_datetime(s).replace(day=1).date()
        except:
            return None

    # ==============================================================================
    # VALIDATION
    # ==============================================================================
    MONTH_MAP = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "mei": 5,
        "jun": 6,
        "jul": 7,
        "agu": 8,
        "sep": 9,
        "okt": 10,
        "nov": 11,
        "des": 12
    }
    def validate_rows(df, branches, variables):

        results = []

        for idx, row in df.iterrows():

            errors = []

            kdo_bsi = str(row.get("kdo_bsi", "")).strip()
            var_code = str(row.get("var_code", "")).strip()

            branch_id = branches.get(kdo_bsi.upper())
            variable_id = variables.get(var_code.upper())

            # Branch validation
            if not kdo_bsi:
                errors.append("KDO BSI kosong")

            elif branch_id is None:
                errors.append(f"Cabang '{kdo_bsi}' tidak ditemukan")

            # Variable validation
            if not var_code:
                errors.append("var_code kosong")

            elif variable_id is None:
                errors.append(f"var_code '{var_code}' tidak ditemukan")

            # Periode validation
            # parsed_periode = parse_periode(row.get("periode"))

            # if parsed_periode is None:
            #     errors.append("periode tidak valid")

            # Value validation
            value = None

            try:
                value_raw = row.get("value")

                if pd.notna(value_raw) and str(value_raw).strip() != "":
                    value = float(value_raw)

            except:
                errors.append("value bukan angka")

            # Target validation
            results.append({
                "row_num": idx + 2,
                "kdo_bsi": kdo_bsi,
                "var_code": var_code,
                "branch_id": branch_id,
                "variable_id": variable_id,
                "periode": selected_period,
                "value": value,
                "status": "error" if errors else "ok",
                "error_message": "; ".join(errors)
            })

        return pd.DataFrame(results)
    

    def validate_target_rows(
        df,
        branches,
        variables,
        selected_year
    ):
        results = []

        for idx, row in df.iterrows():

            kdo_bsi = str(row["kdo_bsi"]).strip()
            var_code = str(row["var_code"]).strip()

            errors = []

            branch_id = branches.get(kdo_bsi.upper())
            variable_id = variables.get(var_code.upper())

            if branch_id is None:
                errors.append("Cabang tidak ditemukan")

            if variable_id is None:
                errors.append("Variable tidak ditemukan")

            results.append({
                "row_num": idx + 2,
                "branch_id": branch_id,
                "variable_id": variable_id,
                "status": "error" if errors else "ok",
                "error_message": "; ".join(errors)
            })

        return pd.DataFrame(results)
    
    def transform_targets(
        df,
        branches,
        variables,
        selected_year
    ):
        records = []

        for _, row in df.iterrows():

            branch_id = branches.get(
                str(row["kdo_bsi"]).strip().upper()
            )

            variable_id = variables.get(
                str(row["var_code"]).strip().upper()
            )

            if not branch_id or not variable_id:
                continue

            for month_name, month_num in MONTH_MAP.items():

                if month_name not in df.columns:
                    continue

                value = row.get(month_name)

                if pd.isna(value):
                    continue

                records.append({
                    "branch_id": branch_id,
                    "variable_id": variable_id,
                    "periode": date(
                        selected_year,
                        month_num,
                        1
                    ),
                    "target_value": float(value)
                })

        return pd.DataFrame(records)
            
    # ==============================================================================
    # UPSERT REALIZATION
    # ==============================================================================
    def upsert_realizations(conn, ok_df):

        rows = ok_df[ok_df["value"].notna()]

        if rows.empty:
            return 0

        sql = """
        INSERT INTO kpi_realizations
        (
            branch_id,
            variable_id,
            periode,
            value
        )
        VALUES (%s,%s,%s,%s)

        ON DUPLICATE KEY UPDATE
            value = VALUES(value)
        """

        data = [
            (
                r.branch_id,
                r.variable_id,
                r.periode,
                r.value
            )
            for r in rows.itertuples()
        ]

        with conn.cursor() as cur:
            cur.executemany(sql, data)

        return len(data)

    # ==============================================================================
    # UPSERT TARGETS
    # ==============================================================================
    def upsert_targets_bulk(
        conn,
        target_rows
    ):
        rows = target_rows[target_rows["target_value"].notna()]

        if rows.empty:
            return 0
        
        sql = """
        INSERT INTO kpi_targets
        (
            branch_id,
            variable_id,
            periode,
            target_value
        )
        VALUES (%s,%s,%s,%s)

        ON DUPLICATE KEY UPDATE
            target_value = VALUES(target_value)
        """
        data = [
            (
                r.branch_id,
                r.variable_id,
                r.periode,
                r.target_value
            )
            for r in target_rows.itertuples()
        ]
        with conn.cursor() as cur:
            cur.executemany(sql, data)

        return len(data)
        

    # ==============================================================================
    # TEMPLATE EXCEL
    # ==============================================================================
    SAMPLE_REALIZATION = [
        {
            "KDO_BSI": "ID0010023",
            "var_code": "CM",
            "value": 1500000000,            
        },
        {
            "KDO_BSI": "ID0010041",
            "var_code": "DPK",
            "value": 5000000000,            
        }
    ]
    
    SAMPLE_TARGET = [
    {
        "KDO_BSI": "ID0010023",
        "var_code": "CM",
        "jan": 1000000000,
        "feb": 1200000000,
        "mar": 1300000000,
        "apr": None,
        "mei": None,
        "jun": None,
        "jul": None,
        "agu": None,
        "sep": None,
        "okt": None,
        "nov": None,
        "des": None,
    }
]

    def make_template_excel_realization():

        output = io.BytesIO()

        with pd.ExcelWriter(output, engine="openpyxl") as writer:

            pd.DataFrame(SAMPLE_REALIZATION).to_excel(
                writer,
                index=False,
                sheet_name="Template KPI"
            )

        return output.getvalue()
    def make_template_excel_target():

        output = io.BytesIO()

        with pd.ExcelWriter(output, engine="openpyxl") as writer:

            pd.DataFrame(SAMPLE_TARGET).to_excel(
                writer,
                index=False,
                sheet_name="Template KPI"
            )

        return output.getvalue()

    # ==============================================================================
    # SESSION STATE
    # ==============================================================================
    if "validated_df" not in st.session_state:
        st.session_state.validated_df = None

    if "import_done" not in st.session_state:
        st.session_state.import_done = False

    # ==============================================================================
    # PAGE HEADER
    # ==============================================================================
    st.title("📥 Import Data KPI")
    st.caption("Upload file Excel KPI cabang")


    # ==============================================================================
    # TEMPLATE DOWNLOAD
    # ==============================================================================
    with st.container():

        st.markdown("### 📄 Download Template")

        col1, col2 = st.columns(2)

        with col1:
            st.download_button(
                "⬇️ Template Realisasi",
                data=make_template_excel_realization(),
                file_name="template_import_realisasi.xlsx"
            )

        with col2:
            st.download_button(
                "⬇️ Template Target",
                data=make_template_excel_target(),
                file_name="template_import_target.xlsx"
            )
    

    # ==============================================================================
    # FILE UPLOAD
    # ==============================================================================
    st.markdown("### 📤 Upload Data Realisasi")
    bulan_list = [
        "Januari","Februari","Maret","April",
        "Mei","Juni","Juli","Agustus",
        "September","Oktober","November","Desember"
    ]

    with col1:
        bulan = st.selectbox(
            "Bulan (Untuk mengatur Bulan Realisasi Saja)",
            bulan_list,
            index=date.today().month - 1
        )

    with col2:
        tahun = st.selectbox(
            "Tahun (Untuk mengatur Tahun Target dan Realisasi)",
            range(2024, 2031),
            index=2
        )

    selected_period = date(
        tahun,
        bulan_list.index(bulan) + 1,
        1
    )
    
    realisasi_uploaded = st.file_uploader(
        "Upload File Excel",
        type=["xlsx"],
        key="upload_realisasi"
    )

    # ==============================================================================
    # PROCESS FILE
    # ==============================================================================
    if realisasi_uploaded:

        try:

            # Read excel
            df_raw = pd.read_excel(
                realisasi_uploaded,
                engine="openpyxl"
            )

            # Lowercase columns
            df_raw.columns = (
                df_raw.columns
                .str.strip()
                .str.lower()
            )

            # Validate columns
            required_columns = {
                "kdo_bsi",
                "var_code",
                "value",                
            }

            missing = required_columns - set(df_raw.columns)

            if missing:

                st.markdown(f"""
                <div class="error-box">
                    <b>Kolom tidak ditemukan:</b><br>
                    {', '.join(missing)}
                </div>
                """, unsafe_allow_html=True)

                st.stop()

            # Convert numeric safely
            df_raw["value"] = pd.to_numeric(
                df_raw["value"],
                errors="coerce"
            )

            # DB lookup
            conn = get_connection()

            branches, variables = load_lookup_data(conn)

            validated = validate_rows(
                df_raw,
                branches,
                variables
            )

            conn.close()

            st.session_state.validated_df = validated

            # Split
            ok_rows = validated[
                validated["status"] == "ok"
            ]

            error_rows = validated[
                validated["status"] == "error"
            ]

            # ==============================================================================
            # METRICS
            # ==============================================================================
            st.markdown("## 🔍 Hasil Validasi")

            c1, c2, c3 = st.columns(3)

            with c1:
                st.markdown(f"""
                <div class="metric">
                    <div class="metric-number">
                        {len(validated)}
                    </div>
                    <div class="metric-label">
                        Total Baris
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with c2:
                st.markdown(f"""
                <div class="metric">
                    <div class="metric-number" style="color:green">
                        {len(ok_rows)}
                    </div>
                    <div class="metric-label">
                        Valid
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with c3:
                st.markdown(f"""
                <div class="metric">
                    <div class="metric-number" style="color:red">
                        {len(error_rows)}
                    </div>
                    <div class="metric-label">
                        Error
                    </div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("---")

            # ==============================================================================
            # ERROR TABLE
            # ==============================================================================
            if not error_rows.empty:

                st.markdown("""
                <div class="warning-box">
                    Ada data yang gagal validasi
                </div>
                """, unsafe_allow_html=True)

                st.dataframe(
                    error_rows[
                        [
                            "row_num",
                            "kdo_bsi",
                            "var_code",
                            "error_message"
                        ]
                    ],
                    use_container_width=True
                )

            # ==============================================================================
            # PREVIEW VALID DATA
            # ==============================================================================
            if not ok_rows.empty:

                st.markdown("""
                <div class="success-box">
                    Data valid siap diimport
                </div>
                """, unsafe_allow_html=True)

                preview = ok_rows[
                    [
                        "kdo_bsi",
                        "var_code",
                        "periode",
                        "value",                        
                    ]
                ]

                st.dataframe(
                    preview,
                    use_container_width=True
                )

                # ==============================================================================
                # IMPORT BUTTON
                # ==============================================================================
                if st.button(
                    "✅ Submit Import",
                    type="primary",
                    use_container_width=True
                ):

                    try:

                        conn = get_connection()

                        n_real = upsert_realizations(
                            conn,
                            ok_rows
                        )

                        # COMMIT dulu sebelum kalkulasi — supaya
                        # load_calculation_data membaca realisasi & target
                        # yang baru saja diinsert, bukan data lama.
                        conn.commit()

                        calculate_period(
                            conn,
                            periode=selected_period
                        )

                        conn.close()                        

                        st.success(
                            f"""
                            Import berhasil!

                            Realisasi: {n_real}                            
                            """
                        )

                    except Exception as e:

                        try:
                            conn.rollback()
                            conn.close()
                        except:
                            pass

                        st.error(f"Gagal import: {e}")

            else:

                st.markdown("""
                <div class="error-box">
                    Tidak ada data valid untuk diimport
                </div>
                """, unsafe_allow_html=True)

        except Exception as e:

            st.error(f"Gagal membaca file Excel: {e}")
    
    st.markdown("---")
    st.markdown("### 📤 Upload Data Target")
    # st.markdown("---")
    
    target_uploaded = st.file_uploader(
        "Upload File Excel",
        type=["xlsx"],
        key="upload_target"
    )
    
    if target_uploaded:

        df_raw = pd.read_excel(
            target_uploaded,
            engine="openpyxl"
        )

        df_raw.columns = (
            df_raw.columns
            .str.strip()
            .str.lower()
        )

        conn = get_connection()

        branches, variables = load_lookup_data(conn)

        conn.close()

        target_rows = transform_targets(
            df_raw,
            branches,
            variables,
            tahun
        )

        st.success(
            f"{len(target_rows)} target berhasil diproses"
        )

        st.dataframe(
            target_rows,
            use_container_width=True
        )

        if st.button(
            "✅ Submit Target",
            type="primary",
            use_container_width=True,
            key="submit_target"
        ):

            try:

                conn = get_connection()

                n_target = upsert_targets_bulk(
                    conn,
                    target_rows
                )

                conn.commit()
                conn.close()

                st.success(
                    f"{n_target} target berhasil diimport"
                )

            except Exception as e:

                try:
                    conn.rollback()
                    conn.close()
                except:
                    pass

                st.error(
                    f"Gagal import target: {e}"
                )
       
