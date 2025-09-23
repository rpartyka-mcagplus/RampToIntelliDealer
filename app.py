import streamlit as st
import pandas as pd

st.set_page_config(page_title="CSV Manipulator", layout="wide")
st.title("📊 CSV Manipulator App")

# File upload
uploaded_file = st.file_uploader("Upload a CSV file", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)

    st.subheader("Preview of Uploaded CSV")
    st.dataframe(df.head())

    # Example operation: Add row sum
    st.subheader("Manipulation Options")
    if st.checkbox("Add Row Sum Column"):
        df["Row_Sum"] = df.sum(axis=1, numeric_only=True)

    if st.checkbox("Drop Missing Values"):
        df = df.dropna()

    if st.checkbox("Convert All Text to Uppercase"):
        df = df.applymap(lambda x: x.upper() if isinstance(x, str) else x)

    st.subheader("Modified CSV")
    st.dataframe(df.head())

    # Download button
    csv_download = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Modified CSV",
        data=csv_download,
        file_name="modified.csv",
        mime="text/csv"
    )
else:
    st.info("👆 Upload a CSV file to get started")
