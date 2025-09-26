import streamlit as st
import pandas as pd
import numpy as np
import os

st.set_page_config(page_title="CSV Manipulator", layout="wide")
st.title("📊 CSV Manipulator App")

def clean_amount_series(s):
    s = s.astype(str).fillna("").str.strip()
    paren_mask = s.str.match(r'^\(.*\)$', na=False)
    cleaned = s.str.replace(r'[\(\)\$,\s]', '', regex=True)
    cleaned = cleaned.str.replace(r'[^0-9.\-]', '', regex=True)
    numeric = pd.to_numeric(cleaned, errors='coerce')
    numeric = numeric.where(~paren_mask, -numeric.abs())
    return numeric

uploaded_file = st.file_uploader("Upload a CSV file", type="csv")

if uploaded_file:
    original_filename = os.path.splitext(uploaded_file.name)[0]

    dtype_cols = [
        "Invoice #", "GL Acct", "Vendor", "Vendor#", "Company", "Division", "Discount Amt",
        "Bank Cost Ctr", "Payables Cost Ctr", "Department", "Location", "Invoice Total",
        "Bank Acct #", "Payables Acct"
    ]
    tmp = pd.read_csv(uploaded_file, nrows=0)
    existing_dtype_cols = [c for c in dtype_cols if c in tmp.columns]
    dtype_map = {col: str for col in existing_dtype_cols}
    uploaded_file.seek(0)
    df = pd.read_csv(uploaded_file, dtype=dtype_map)

    df = df.dropna(how="all").reset_index(drop=True)
    df["_original_index"] = np.arange(len(df))

    # Make GL Acct string
    if "GL Acct" in df.columns:
        df["GL Acct"] = df["GL Acct"].astype(str)

    # Filter out GL Acct 99999 rows
    filtered_out = pd.DataFrame()
    if "GL Acct" in df.columns:
        filtered_out = df[df["GL Acct"] == "99999"].copy()
        df = df[df["GL Acct"] != "99999"].copy()

    st.subheader("Preview of Uploaded CSV")
    st.dataframe(df)

    st.subheader("Manipulation Options")

    # Format Purchase Date and fill empty Invoice #
    if st.checkbox("Format 'Purchase Date' as yyyyMMdd and fill empty 'Invoice #'", value=True):
        if "Purchase Date" in df.columns:
            df["Purchase Date"] = pd.to_datetime(df["Purchase Date"], errors="coerce")
            df["Purchase Date"] = df["Purchase Date"].dt.strftime("%Y%m%d")
        else:
            df["Purchase Date"] = ""
        if "Invoice #" in df.columns and "Vendor" in df.columns:
            mask_empty_invoice = df["Invoice #"].isna() | (df["Invoice #"].astype(str).str.strip() == "")
            df.loc[mask_empty_invoice, "Invoice #"] = (
                df.loc[mask_empty_invoice, "Vendor"].astype(str) + "_" + df.loc[mask_empty_invoice, "Purchase Date"].astype(str)
            )
            df["Invoice #"] = df["Invoice #"].astype(str)
        else:
            if "Invoice #" not in df.columns:
                df["Invoice #"] = ""
            if "Vendor" not in df.columns:
                df["Vendor"] = ""

    # Normalize Location
    if "Location" not in df.columns:
        df["Location"] = ""
    df["Location"] = df["Location"].astype(str).str.strip().replace("", np.nan)
    df["Location"] = df["Location"].fillna("").apply(lambda x: x.zfill(2) if x != "" else "")

    # Ensure Bank/Payables columns exist
    for col in ["Bank Cost Ctr", "Bank Acct #", "Payables Cost Ctr", "Payables Acct"]:
        if col not in df.columns:
            df[col] = None

    # Bank/Payables assignment
    mask_01_03 = df["Location"].isin(["01", "03"])
    mask_02_04 = df["Location"].isin(["02", "04"])
    df.loc[mask_01_03, "Bank Cost Ctr"] = "001"
    df.loc[mask_01_03, "Bank Acct #"] = "10130"
    df.loc[mask_01_03, "Payables Cost Ctr"] = "000"
    df.loc[mask_01_03, "Payables Acct"] = "20010"
    df.loc[mask_02_04, "Bank Cost Ctr"] = "000"
    df.loc[mask_02_04, "Bank Acct #"] = "10138"
    df.loc[mask_02_04, "Payables Cost Ctr"] = "000"
    df.loc[mask_02_04, "Payables Acct"] = "20011"

    # Prepare GL Amt numeric
    if "GL Amt" in df.columns:
        df["_GL_Amt_numeric"] = clean_amount_series(df["GL Amt"]).fillna(0.0)
    else:
        df["_GL_Amt_numeric"] = 0.0

    # Build GL Cost Ctr = Department + Location (no leading zeros on Department)
    if "Department" in df.columns and "Location" in df.columns:
        df["GL Cost Ctr"] = df["Department"].astype(str) + df["Location"].astype(str)

    # ---------- RECORD ID & Invoice # assignment ----------
    df["Record ID"] = np.nan
    loc_suffix_map = {"01": "W", "03": "M", "02": "F", "04": "G"}
    result_rows = []
    record_id = 0

    # Process each invoice in original order
    for invoice in df.sort_values("_original_index")["Invoice #"].unique():
        inv_df = df[df["Invoice #"] == invoice]
        bank_counts = inv_df["Bank Acct #"].nunique()

        if bank_counts == 1:
            # Single Bank Acct # → one Record ID
            record_id += 1
            group = inv_df.copy()
            unique_locs = [loc for loc in pd.unique(group["Location"]) if loc in loc_suffix_map]
            suffixes = "".join(sorted([loc_suffix_map[loc] for loc in unique_locs]))
            new_invoice = str(invoice).strip()
            if suffixes:
                new_invoice = f"{new_invoice} {suffixes}"
            group["Invoice #"] = new_invoice
            group["Record ID"] = record_id
            result_rows.append(group)
        else:
            # Multiple Bank Acct #s → sort by Bank Acct # within invoice, separate Record ID per Bank Acct #
            for bank, group in inv_df.groupby("Bank Acct #", sort=False):
                record_id += 1
                group = group.copy()
                unique_locs = [loc for loc in pd.unique(group["Location"]) if loc in loc_suffix_map]
                suffixes = "".join(sorted([loc_suffix_map[loc] for loc in unique_locs]))
                new_invoice = str(invoice).strip()
                if suffixes:
                    new_invoice = f"{new_invoice} {suffixes}"
                group["Invoice #"] = new_invoice
                group["Record ID"] = record_id
                result_rows.append(group)

    # Combine all rows, preserving original order where possible
    df = pd.concat(result_rows).sort_values("Record ID").reset_index(drop=True)

    # Invoice Total = sum of GL Amt per Record ID
    if "Invoice Total" not in df.columns:
        df["Invoice Total"] = None
    df["Invoice Total"] = df.groupby("Record ID")["_GL_Amt_numeric"].transform("sum").apply(lambda x: f"{x:.2f}")

    # GL Amt formatted
    df["GL Amt"] = df["_GL_Amt_numeric"].apply(lambda x: f"{x:.2f}")

    # Clear specified columns
    for col in ["Discount Amt", "Payables Cost Ctr", "Discount Cost Ctr", "Discount Acct"]:
        if col in df.columns:
            df[col] = None

    # Drop helper/unwanted columns
    df = df.drop(columns=["_GL_Amt_numeric", "_original_index",
                          "Department", "Location", "TransactionID", "Vendor", "Row_Sum"], errors="ignore").reset_index(drop=True)

    # Convert all text to uppercase
    if st.checkbox("Convert all text to UPPERCASE", value=True):
        for col in df.select_dtypes(include='object').columns:
            df[col] = df[col].str.upper()

    st.subheader("Modified CSV Preview")
    st.dataframe(df)

    st.subheader("Record ID Summary (Quick QA)")
    summary_cols = ["Record ID", "Invoice #", "Bank Acct #", "Invoice Total"]
    summary_cols = [col for col in summary_cols if col in df.columns]

    if summary_cols:
        summary_df = df[summary_cols].drop_duplicates(subset=["Record ID", "Bank Acct #"]).sort_values("Record ID").reset_index(drop=True)
        st.dataframe(summary_df)


    # Download buttons
    modified_csv_name = f"IntelliDealer_Upload_{uploaded_file.name}"
    csv_download = df.to_csv(index=False, encoding="utf-8").encode("utf-8")
    st.download_button(label="📥 Download Modified CSV",
                       data=csv_download,
                       file_name=modified_csv_name,
                       mime="text/csv")

    if not filtered_out.empty:
        filtered_name = f"{original_filename}_PARTS.csv"
        filtered_download = filtered_out.to_csv(index=False, encoding="utf-8").encode("utf-8")
        st.download_button(label="📥 Download GL Acct 99999 Rows",
                           data=filtered_download,
                           file_name=filtered_name,
                           mime="text/csv")
else:
    st.info("👆 Upload a CSV file to get started")
