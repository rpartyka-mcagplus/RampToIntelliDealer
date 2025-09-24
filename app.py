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
    original_filename = os.path.splitext(uploaded_file.name)[0]  # remove extension for reuse

    dtype_cols = [
        "Invoice #", "GL Acct", "Vendor", "Vendor#", "Company", "Division", "Discount Amt",
        "Bank Cost Ctr", "Payables Cost Ctr", "Department", "Location"
    ]
    tmp = pd.read_csv(uploaded_file, nrows=0)
    existing_dtype_cols = [c for c in dtype_cols if c in tmp.columns]
    dtype_map = {col: str for col in existing_dtype_cols}
    uploaded_file.seek(0)
    df = pd.read_csv(uploaded_file, dtype=dtype_map)

    df = df.dropna(how="all").reset_index(drop=True)
    st.subheader("Preview of Uploaded CSV")
    st.dataframe(df)

    df["_original_index"] = range(len(df))

    if "GL Acct" in df.columns:
        df["GL Acct"] = df["GL Acct"].astype(str)

    filtered_out = pd.DataFrame()
    if "GL Acct" in df.columns:
        filtered_out = df[df["GL Acct"] == "99999"].copy()
        df = df[df["GL Acct"] != "99999"].copy()

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
            df["Invoice #"] = ""
            df["Vendor"] = ""

    # Add Record ID increment
    if st.checkbox("Add Record ID (increments when Invoice # changes)", value=True):
        df = df.sort_values("_original_index").reset_index(drop=True)
        if "Invoice #" not in df.columns:
            df["Invoice #"] = ""
        df["Record ID"] = (df["Invoice #"] != df["Invoice #"].shift()).cumsum()
    else:
        if "Record ID" not in df.columns:
            df["Record ID"] = np.nan

    if "Department" not in df.columns:
        df["Department"] = ""
    if "Location" not in df.columns:
        df["Location"] = ""
    df["GL Cost Ctr"] = df["Department"].astype(str) + df["Location"].astype(str)

    # Clean GL Amt for all rows
    df["_GL_Amt_numeric"] = clean_amount_series(df["GL Amt"]) if "GL Amt" in df.columns else 0.0
    df["GL Amt"] = df["_GL_Amt_numeric"].apply(lambda x: f"{x:.2f}")

    # Clear specified columns for all rows
    for col in ["Discount Amt", "Payables Cost Ctr", "Discount Cost Ctr", "Discount Acct"]:
        if col in df.columns:
            df[col] = None

    # Update Bank Cost Ctr based on Location for all non-balancing rows
    if "Location" in df.columns and "Bank Cost Ctr" in df.columns:
        df.loc[df["Location"].isin(["01","03"]), "Bank Cost Ctr"] = "001"
        df.loc[df["Location"].isin(["02","04"]), "Bank Cost Ctr"] = "000"

    # Prepare numeric Discount Amt for balancing row
    df["_Discount_Amt_numeric"] = clean_amount_series(df["Discount Amt"]) if "Discount Amt" in df.columns else 0.0

    # Insert balancing rows
    if "Record ID" in df.columns:
        new_rows = []
        for rid, group in df.groupby("Record ID", sort=False):
            balancing_row = {col: None for col in df.columns}
            balancing_row["Record ID"] = rid
            balancing_row["GL Amt"] = f"{-group['_GL_Amt_numeric'].sum():.2f}" if "_GL_Amt_numeric" in group.columns else None
            balancing_row["Discount Amt"] = None
            balancing_row["Company"] = group["Company"].iloc[0] if "Company" in group.columns else None
            balancing_row["Division"] = group["Division"].iloc[0] if "Division" in group.columns else None
            balancing_row["Purchase Date"] = group["Purchase Date"].iloc[0] if "Purchase Date" in group.columns else None
            balancing_row["Vendor#"] = "BANK" if "Vendor#" in df.columns else None
            balancing_row["Invoice #"] = "RAMP PAYMENT" if "Invoice #" in df.columns else None
            balancing_row["GL Cost Ctr"] = None
            balancing_row["Payables Cost Ctr"] = None
            balancing_row["Discount Cost Ctr"] = None
            balancing_row["Discount Acct"] = None
            # Bank Cost Ctr removed from balancing rows
            new_rows.append(pd.DataFrame([balancing_row]))
            new_rows.append(group.drop(columns=["_GL_Amt_numeric","_Discount_Amt_numeric"], errors="ignore"))
        df = pd.concat(new_rows, ignore_index=True, sort=False)
    else:
        df = df.drop(columns=["_GL_Amt_numeric","_Discount_Amt_numeric"], errors="ignore")

    # Remove helper and unwanted columns
    df = df.drop(columns=["_GL_Amt_numeric","_Discount_Amt_numeric","_original_index",
                          "Department","Location","TransactionID","Vendor","Row_Sum"], errors="ignore").reset_index(drop=True)

    # Convert all text to uppercase (checked by default)
    if st.checkbox("Convert all text to UPPERCASE", value=True):
        for col in df.select_dtypes(include='object').columns:
            df[col] = df[col].str.upper()

    st.subheader("Modified CSV Preview")
    st.dataframe(df)

    # Updated download buttons with dynamic file names
    modified_csv_name = f"IntelliDealer_Upload_{uploaded_file.name}"
    csv_download = df.to_csv(index=False, encoding="utf-8").encode("utf-8")
    st.download_button(
        label="📥 Download Modified CSV",
        data=csv_download,
        file_name=modified_csv_name,
        mime="text/csv"
    )

    if not filtered_out.empty:
        filtered_name = f"{original_filename}_PARTS.csv"
        filtered_download = filtered_out.to_csv(index=False, encoding="utf-8").encode("utf-8")
        st.download_button(
            label="📥 Download GL Acct 99999 Rows",
            data=filtered_download,
            file_name=filtered_name,
            mime="text/csv"
        )

else:
    st.info("👆 Upload a CSV file to get started")
