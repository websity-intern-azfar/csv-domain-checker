# app.py
import asyncio, pathlib, subprocess, pandas as pd, streamlit as st
import nest_asyncio; nest_asyncio.apply()           # allow nested event loops

from email_checker import process_async             # reuse your async worker

# ---------------------------------------------------------------------------
# One‑time browser install (first build only)
# ---------------------------------------------------------------------------
CACHE = pathlib.Path.home() / ".cache/ms-playwright"
if not CACHE.exists():                               # Streamlit Cloud's container
    with st.spinner("Installing Playwright browser — first deploy only…"):
        # Installs Chromium (~140 MB) into ~/.cache/ms-playwright
        subprocess.run(["playwright", "install", "chromium"], check=True)

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Email ↔ Company Domain Checker", page_icon="🔍")
st.title("Email ↔ Company Domain Checker")

st.markdown(
    "Upload a CSV that contains **`Email Domain`** and **`Company Domain`** "
    "columns. The app will mark each row “Pass” or “Fail” in an `EmailMatch` "
    "column and add a short diagnostic note (`RetryNote`)."
)

uploaded = st.file_uploader("Choose a CSV file", type="csv")

# Optional parameters for power‑users
with st.expander("Advanced settings", False):
    timeout_ms  = st.slider("Per‑URL timeout (ms)",     5_000, 120_000, 10_000, 1000)
    concurrency = st.slider("Parallel browser tabs",    1, 15, 10)

if uploaded:
    df = pd.read_csv(uploaded, dtype=str)
    st.subheader("Preview (first 5 rows)")
    st.dataframe(df.head())

    if st.button("Run check", type="primary"):
        # Determine which rows need work
        if "EmailMatch" not in df.columns:
            df["EmailMatch"] = ""
        mask = df["EmailMatch"].isin(["", "Fail"])

        if not mask.any():
            st.success("All rows already marked **Pass** – nothing to do.")
        else:
            st.info(f"Re‑checking **{mask.sum()}** rows…")
            loop = asyncio.get_event_loop()
            loop.run_until_complete(
                process_async(df, mask, concurrency=concurrency, timeout_ms=timeout_ms)
            )
            st.success("Finished ✔️")

        st.subheader("Result sample")
        st.dataframe(df.head())

        st.download_button(
            "Download processed CSV",
            df.to_csv(index=False).encode(),
            "checked.csv",
            "text/csv",
        )
