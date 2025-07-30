# app.py  –  Streamlit UI for Email ↔ Company Domain checker
#
# • Lets you choose up to **10 retry rounds**.
# • Lets you set an arbitrary **base timeout (ms)** and a **multiplier**
#   applied on every retry:  timeout = base_timeout × (multiplier^retry_index).
#
# Prerequisites in your repo:
#   ├─ email_checker.py          (logic you already have)
#   ├─ requirements.txt
#   ├─ packages.txt
#   └─ runtime.txt               (python‑3.12.x or lower for Playwright wheels)

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
    "Upload a CSV that contains **`Email Domain`** and **`Company Domain`**. "
    "The app marks each row **Pass/Fail** in `EmailMatch`, adds a `RetryNote`, "
    "and returns a trimmed CSV with six columns only."
)

uploaded = st.file_uploader("Choose a CSV file", type="csv")

# ————— Sidebar ————————————————————————————————————————————————
with st.sidebar:
    st.header("Settings")

    base_timeout = st.number_input(
        "Base per‑URL timeout (ms)",
        min_value=1_000, max_value=300_000, value=10_000, step=1_000
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

        # ——— initial pass ———
        mask = df["EmailMatch"].isin(["", "Fail"])
        if mask.any():
            st.info(f"Initial pass → processing {mask.sum()} rows …")
            loop.run_until_complete(
                process_async(df, mask,
                              concurrency=concurrency,
                              timeout_ms=int(base_timeout))
            )
        else:
            st.success("All rows already marked Pass – nothing to do.")

        # ——— retries ———
        for r in range(1, retries + 1):
            fails = df["EmailMatch"] == "Fail"
            if not fails.any():
                break                                   # everything fixed
            t_ms = int(base_timeout * (timeout_mult ** r))
            st.info(f"Retry {r}/{retries} → {fails.sum()} rows | timeout {t_ms//1000}s")
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
