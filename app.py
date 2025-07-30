# app.py  –  Streamlit UI for Email ↔ Company Domain checker
#
# • Lets you pick **up to 10 retry rounds**.
# • Base timeout is now set **in seconds** via the sidebar; internally we
#   convert to milliseconds for Playwright.
# • Timeout for retry *n* = base_timeout_sec × (multiplier ** n).
#   (Playwright still receives milliseconds.)
#
# Repo prerequisites (unchanged):
#   email_checker.py, requirements.txt, packages.txt, runtime.txt  (Python ≤ 3.12)

import asyncio, pathlib, subprocess, pandas as pd, streamlit as st
import nest_asyncio; nest_asyncio.apply()

from email_checker import process_async                     # async worker

# ───────────────────────── First‑run browser install ─────────────────────────
CACHE = pathlib.Path.home() / ".cache/ms-playwright"
if not CACHE.exists():                                       # Streamlit Cloud only
    with st.spinner("Installing Playwright Chromium (first deploy)…"):
        subprocess.run(["playwright", "install", "chromium"], check=True)

# ────────────────────────────── UI layout ────────────────────────────────────
st.set_page_config(page_title="Email ↔ Company Domain Checker", page_icon="🔍")
st.title("Email ↔ Company Domain Checker")

st.markdown(
    "Upload a CSV containing **`Email Domain`** and **`Company Domain`**. "
    "The app adds/updates `EmailMatch` & `RetryNote`, then lets you "
    "download a file with only the six columns you need."
)

uploaded = st.file_uploader("Choose a CSV file", type="csv")

# ————— Sidebar ————————————————————————————————————————————————
with st.sidebar:
    st.header("Settings")

    base_timeout_sec = st.number_input(
        "Base per‑URL timeout (seconds)",
        min_value=1, max_value=300, value=10, step=1
    )

    timeout_mult = st.number_input(
        "Timeout multiplier per retry",
        min_value=1.0, max_value=5.0, value=2.0, step=0.1, format="%.1f"
    )

    retries = st.slider(
        "Retry rounds for **Fail** rows",
        0, 10, 2,
        help="0 = no retry, 10 = up to ten passes after the initial run"
    )

    concurrency = st.slider("Parallel browser tabs", 1, 20, 10)

# ————— Main flow ————————————————————————————————————————————————
if uploaded:
    df = pd.read_csv(uploaded, dtype=str)
    st.subheader("Preview (first 5 rows)")
    st.dataframe(df.head())

    if st.button("Run check", type="primary"):
        loop = asyncio.get_event_loop()

        # Ensure required columns exist
        for col in ("EmailMatch", "RetryNote"):
            if col not in df.columns:
                df[col] = ""

        base_timeout_ms = int(base_timeout_sec * 1000)

        # ——— initial pass ———
        mask = df["EmailMatch"].isin(["", "Fail"])
        if mask.any():
            st.info(f"Initial pass → {mask.sum()} rows | timeout {base_timeout_sec}s")
            loop.run_until_complete(
                process_async(df, mask,
                              concurrency=concurrency,
                              timeout_ms=base_timeout_ms)
            )
        else:
            st.success("All rows already marked Pass – nothing to do.")

        # ——— retries ———
        for r in range(1, retries + 1):
            fails = df["EmailMatch"] == "Fail"
            if not fails.any():
                break
            t_sec = base_timeout_sec * (timeout_mult ** r)
            t_ms  = int(t_sec * 1000)
            st.info(f"Retry {r}/{retries} → {fails.sum()} rows | timeout {t_sec:.1f}s")
            loop.run_until_complete(
                process_async(df, fails,
                              concurrency=concurrency,
                              timeout_ms=t_ms)
            )

        st.success("All passes complete ✔️")

        # ——— output six columns ———
        cols = ["Company Name", "Full Name",
                "Company Domain", "Email Domain",
                "EmailMatch", "RetryNote"]
        df_out = df.reindex(columns=cols, copy=False)

        st.subheader("Result sample")
        st.dataframe(df_out.head())

        st.download_button(
            label="Download processed CSV",
            data=df_out.to_csv(index=False).encode(),
            file_name="checked.csv",
            mime="text/csv",
        )
