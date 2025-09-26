import streamlit as st
import pandas as pd
import numpy as np
import io
import os

st.set_page_config(page_title="CSV Manipulator", layout="wide")
st.title("📊 CSV Manipulator App")

def clean_amount_series(s):
    """
    Convert amount-like strings into numeric floats.
    Handles: commas, dollar signs, parentheses for negatives, spaces.
    """
    s = s.astype(str).fillna("").str.strip()
    paren_mask = s.str.match(r'^\(.*\)$', na=False)
    cleaned = s.str.replace(r'[\(\)\$,\s]', '', regex=True)
    cleaned = cleaned.str.replace(r'[^0-9.\-]', '', regex=True)
    numeric = pd.to_numeric(cleaned, errors='coerce')
    numeric = numeric.where(~paren_mask, -numeric.abs())
    return numeric

uploaded_file = st.file_uploader("Upload a CSV file", type="csv")

# Option: uppercase by default
uppercase = st.checkbox("Convert all text to UPPERCASE", value=True)

if uploaded_file:
    original_filename = os.path.splitext(uploaded_file.name)[0]

    # Read everything as strings so leading zeros are preserved for key columns
    df = pd.read_csv(uploaded_file, dtype=str).fillna("")

    # Normalize header names (trim spaces)
    df.columns = df.columns.str.strip()

    # Keep original order index
    df["_original_index"] = np.arange(len(df))

    # --- Separate out GL Acct = 99999 rows early (export parts file later) ---
    parts_df = pd.DataFrame()
    if "GL Acct" in df.columns:
        parts_df = df[df["GL Acct"] == "99999"].copy()
        df = df[df["GL Acct"] != "99999"].copy()

    st.subheader("Preview of Uploaded CSV")
    st.dataframe(df)

    st.subheader("Manipulation Options")

    # --- Purchase Date formatting and fill empty Invoice # ---
    # Format Purchase Date to yyyyMMdd (if exists)
    if "Purchase Date" in df.columns:
        df["Purchase Date"] = pd.to_datetime(df["Purchase Date"], errors="coerce").dt.strftime("%Y%m%d")
        df["Purchase Date"] = df["Purchase Date"].fillna("")
    else:
        df["Purchase Date"] = ""

    # Fill empty Invoice # with Vendor_yyyyMMdd; support both "Vendor" and "Vendor#"
    vendor_col = "Vendor" if "Vendor" in df.columns else ("Vendor#" if "Vendor#" in df.columns else None)
    if "Invoice #" not in df.columns:
        df["Invoice #"] = ""
    if vendor_col:
        mask_empty_invoice = (df["Invoice #"].astype(str).str.strip() == "")
        df.loc[mask_empty_invoice, "Invoice #"] = (
            df.loc[mask_empty_invoice, vendor_col].astype(str) + "_" + df.loc[mask_empty_invoice, "Purchase Date"].astype(str)
        )
    df["Invoice #"] = df["Invoice #"].astype(str)

    # --- Normalize Location (preserve leading zero if present) ---
    if "Location" not in df.columns:
        df["Location"] = ""
    df["Location"] = df["Location"].astype(str).str.strip().replace("", np.nan)
    df["Location"] = df["Location"].fillna("").apply(lambda x: x.zfill(2) if x != "" else "")

    # --- Ensure Bank/Payables columns exist BEFORE assigning values ---
    for col in ["Bank Cost Ctr", "Bank Acct #", "Payables Cost Ctr", "Payables Acct"]:
        if col not in df.columns:
            df[col] = ""

    # --- Assign Bank & Payables values based on Location (applies to all rows) ---
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

    # --- Prepare numeric GL Amt helper for accurate sums ---
    if "GL Amt" in df.columns:
        df["_GL_Amt_numeric"] = clean_amount_series(df["GL Amt"]).fillna(0.0)
    else:
        df["_GL_Amt_numeric"] = 0.0

    # --- Build GL Cost Ctr before we drop Department/Location ---
    if "Department" in df.columns and "Location" in df.columns:
        # Department kept as-is (no extra leading zeros), Location kept as-is
        df["GL Cost Ctr"] = df["Department"].astype(str) + df["Location"].astype(str)

    # --- Clear only the specified discount-related columns (KEEP Payables Cost Ctr) ---
    for col in ["Discount Amt", "Discount Cost Ctr", "Discount Acct"]:
        if col in df.columns:
            df[col] = ""

    # ---------- RECORD ID assignment (one per Invoice, except multiple Bank Acct# => multiple IDs) ----------
    df["Record ID"] = np.nan
    loc_suffix_map = {"01": "W", "03": "M", "02": "F", "04": "G"}

    result_groups = []
    record_id_counter = 0

    # Process invoices in the order they originally appeared
    for invoice in df.sort_values("_original_index")["Invoice #"].unique():
        inv_df = df[df["Invoice #"] == invoice]
        # Count unique Bank Acct # for this invoice
        unique_bank_count = inv_df["Bank Acct #"].nunique()

        if unique_bank_count <= 1:
            # Single Bank Acct #: treat entire invoice as one Record ID
            record_id_counter += 1
            group = inv_df.copy()
            unique_locs = [loc for loc in pd.unique(group["Location"]) if loc in loc_suffix_map]
            suffixes = "".join(sorted([loc_suffix_map[loc] for loc in unique_locs]))
            new_invoice_label = str(invoice).strip()
            if suffixes:
                new_invoice_label = f"{new_invoice_label} {suffixes}"
            group["Invoice #"] = new_invoice_label
            group["Record ID"] = record_id_counter
            result_groups.append(group)
        else:
            # Multiple Bank Acct #: create one Record ID per Bank Acct # and sort rows by Bank Acct # within this invoice
            # Preserve original order within each bank group
            for bank_acct, sub in inv_df.groupby("Bank Acct #", sort=False):
                record_id_counter += 1
                group = sub.copy()
                unique_locs = [loc for loc in pd.unique(group["Location"]) if loc in loc_suffix_map]
                suffixes = "".join(sorted([loc_suffix_map[loc] for loc in unique_locs]))
                new_invoice_label = str(invoice).strip()
                if suffixes:
                    new_invoice_label = f"{new_invoice_label} {suffixes}"
                group["Invoice #"] = new_invoice_label
                group["Record ID"] = record_id_counter
                result_groups.append(group)

    # Combine all result groups and then sort by Record ID so rows with same Record ID are sequential
    df = pd.concat(result_groups, ignore_index=True, sort=False)
    df = df.sort_values("Record ID").reset_index(drop=True)

    # --- Overwrite Invoice Total with sum of GL Amt per Record ID (format as 2 decimals) ---
    if "Invoice Total" not in df.columns:
        df["Invoice Total"] = ""
    if "Record ID" in df.columns:
        invoice_totals = df.groupby("Record ID")["_GL_Amt_numeric"].transform("sum")
        df["Invoice Total"] = invoice_totals.apply(lambda x: f"{x:.2f}")

    # Format GL Amt as 2-decimal string (no dollar signs)
    df["GL Amt"] = df["_GL_Amt_numeric"].apply(lambda x: f"{x:.2f}")

    # Drop helper columns and optionally drop originals we don't want exported
    drop_cols = ["_GL_Amt_numeric", "_original_index", "Department", "Location", "TransactionID", "Vendor", "Row_Sum"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore").reset_index(drop=True)

    # Apply uppercase if selected (do parts_df too)
    if uppercase:
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].str.upper()
        if not parts_df.empty:
            for col in parts_df.select_dtypes(include="object").columns:
                parts_df[col] = parts_df[col].str.upper()

    # --- Preview and QA summary ---
    st.subheader("Modified CSV Preview")
    st.dataframe(df)

    st.subheader("Record ID Summary (Quick QA)")
    summary_cols = ["Record ID", "Invoice #", "Bank Acct #", "Invoice Total"]
    summary_cols = [c for c in summary_cols if c in df.columns]
    if summary_cols:
        summary_df = df[summary_cols].drop_duplicates(subset=["Record ID", "Bank Acct #"]).sort_values("Record ID").reset_index(drop=True)
        st.dataframe(summary_df)

    # --- Downloads ---
    modified_csv_name = f"IntelliDealer_Upload_{uploaded_file.name}"
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(label="📥 Download Modified CSV", data=csv_bytes, file_name=modified_csv_name, mime="text/csv")

    if not parts_df.empty:
        parts_name = f"{original_filename}_PARTS.csv"
        parts_bytes = parts_df.to_csv(index=False).encode("utf-8")
        st.download_button(label="📥 Download GL Acct 99999 Rows", data=parts_bytes, file_name=parts_name, mime="text/csv")

else:
    st.info("👆 Upload a CSV file to get started")
