# app.py  –  Streamlit UI for Email ↔ Company Domain checker
# Requires: email_checker.py, requirements.txt, packages.txt, runtime.txt (Python ≤ 3.12)

import asyncio, pathlib, subprocess, pandas as pd, streamlit as st
import nest_asyncio; nest_asyncio.apply()

from email_checker import process_async                   # your async worker

# ───────────────────────── first‑run browser install ─────────────────────────
CACHE = pathlib.Path.home() / ".cache/ms-playwright"
if not CACHE.exists():
    with st.spinner("Installing Playwright browser (first deploy only)…"):
        subprocess.run(["playwright", "install", "chromium"], check=True)

# ────────────────────────────── UI layout ────────────────────────────────────
st.set_page_config(page_title="Email ↔ Company Domain Checker", page_icon="🔍")
st.title("Email ↔ Company Domain Checker")

st.markdown(
    "Upload a CSV containing **`Email Domain`** and **`Company Domain`**. "
    "The app will add/overwrite `EmailMatch` and `RetryNote`, then let you "
    "download a file with *only* the six columns you need."
)

uploaded = st.file_uploader("Choose a CSV file", type="csv")

with st.expander("Advanced settings", False):
    timeout_ms  = st.slider("Per‑URL timeout (ms)",     5_000, 120_000, 10_000, 1000)
    concurrency = st.slider("Parallel browser tabs",    1, 15, 10)

if uploaded:
    df = pd.read_csv(uploaded, dtype=str)
    st.subheader("Preview (first 5 rows)")
    st.dataframe(df.head())

    if st.button("Run check", type="primary"):
        # make sure EmailMatch column exists
        if "EmailMatch" not in df.columns:
            df["EmailMatch"] = ""
        mask = df["EmailMatch"].isin(["", "Fail"])

        if not mask.any():
            st.success("All rows already marked Pass – nothing to do.")
        else:
            st.info(f"Processing {mask.sum()} rows …")
            asyncio.get_event_loop().run_until_complete(
                process_async(df, mask, concurrency=concurrency, timeout_ms=timeout_ms)
            )
            st.success("Finished ✔️")

        # ───────── filter & order columns ─────────
        cols = ["Company Name", "Full Name",
                "Company Domain", "Email Domain",
                "EmailMatch", "RetryNote"]
        df_out = df.reindex(columns=cols, copy=False)

        st.subheader("Result sample")
        st.dataframe(df_out.head())

        st.download_button(
            "Download processed CSV",
            df_out.to_csv(index=False).encode(),
            "checked.csv",
            "text/csv",
        )

