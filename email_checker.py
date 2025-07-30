#!/usr/bin/env python
"""
email_checker.py  –  Asynchronous “Email Domain ↔ Company Domain” checker
──────────────────────────────────────────────────────────────────────────
▶  Stand‑alone usage
    $ python email_checker.py input.csv [output.csv]

▶  Import in other code (e.g. Streamlit)
    from email_checker import process_async, run_file
"""

from __future__ import annotations

import sys, csv, asyncio, contextlib
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import nest_asyncio
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from tqdm.asyncio import tqdm_asyncio

# ──────────  patch nested event loops (Streamlit, Jupyter)  ──────────
nest_asyncio.apply()

# ──────────  helpers  ──────────
def norm_url(u: str | None) -> str | None:
    """Ensure URL has scheme, return None if invalid/blank."""
    if u is None or not isinstance(u, str) or not u.strip():
        return None
    u = u.strip()
    if not u.lower().startswith(("http://", "https://")):
        u = "http://" + u
    return u

def host(u: str | None) -> str:
    """Extract netloc minus leading www."""
    return urlparse(u).netloc.lower().lstrip("www.") if u else ""

@contextlib.asynccontextmanager
async def browser_ctx():
    """Launch a headless Chromium; auto‑close at exit."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        try:
            yield browser
        finally:
            await browser.close()

async def fetch_html(page, url: str, timeout_ms=100_000) -> dict:
    """Load a page, return HTML (or error)."""
    # Abort images/fonts for speed
    await page.route("**/*.{png,jpg,jpeg,svg,webp,woff,woff2}", lambda r: asyncio.create_task(r.abort()))
    try:
        resp = await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
        html = (await page.content()).strip()
        status = resp.status if resp else None
        return dict(ok=True, html=html, err="", status=status, final=page.url)
    except PWTimeout:
        return dict(ok=False, html="", err="Timeout", status=None, final="")
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status", None)
        return dict(ok=False, html="", err=type(e).__name__, status=status, final="")

async def compare_pair(
    browser,
    email_url: str,
    comp_url: str,
    timeout_ms: int = 10_000,
) -> tuple[str, bool]:
    """
    Compare one Email Domain vs Company Domain.

    Returns (note, bool_pass)
    """
    u1, u2 = norm_url(email_url), norm_url(comp_url)
    if not u1 or not u2:
        return "FetchErr:MissingURL", False

    same_host = host(u1) == host(u2)
    page1, page2 = await asyncio.gather(browser.new_page(), browser.new_page())

    r1, r2 = await asyncio.gather(
        fetch_html(page1, u1, timeout_ms),
        fetch_html(page2, u2, timeout_ms),
    )
    await asyncio.gather(page1.close(), page2.close())

    # Any fetch failed?
    if not r1["ok"] or not r2["ok"]:
        return f"FetchErr:{r1['err'] or r1['status']}|{r2['err'] or r2['status']}", False

    # Heuristics
    if same_host or r1["html"] == r2["html"]:
        return "Pass", True
    if not r1["html"] or not r2["html"]:
        return "EmptyBody", False
    return "StillDiff", False

# ──────────  asynchronous worker over DataFrame  ──────────
async def process_async(
    df: pd.DataFrame,
    mask: pd.Series,
    *,
    concurrency: int = 10,
    timeout_ms: int = 100_000,
) -> pd.DataFrame:
    """
    Given *df* and a boolean *mask* of rows to process,
    fill / update columns **EmailMatch** and **RetryNote**.
    """
    sem = asyncio.Semaphore(concurrency)
    results: dict[int, tuple[str, bool]] = {}

    async with browser_ctx() as br:

        async def worker(idx: int, row: pd.Series):
            async with sem:
                note, ok = await compare_pair(
                    br,
                    row["Email Domain"],
                    row["Company Domain"],
                    timeout_ms,
                )
                results[idx] = (note, ok)

        # Kick off workers
        tasks = [
            asyncio.create_task(worker(i, r))
            for i, r in df.loc[mask].iterrows()
        ]
        await tqdm_asyncio.gather(*tasks)

    # Write results back
    for idx, (note, ok) in results.items():
        df.at[idx, "RetryNote"]  = note
        df.at[idx, "EmailMatch"] = "Pass" if ok else "Fail"
    return df

# ──────────  top‑level helper – for CLI *and* for Streamlit  ──────────
def run_file(in_path: Path, out_path: Path | None = None) -> None:
    """
    Read CSV → run checker → write CSV.
    If *out_path* is None, overwrite *in_path*.
    """
    df = pd.read_csv(in_path, dtype=str)

    # Ensure required columns exist
    if "EmailMatch" not in df.columns:
        df["EmailMatch"] = ""
    if "RetryNote" not in df.columns:
        df["RetryNote"] = ""

    # Normalize any existing values
    df["EmailMatch"] = (
        df["EmailMatch"].astype(str)
        .str.strip()
        .str.capitalize()
        .replace({"Nan": ""})
    )

    # Rows needing (re)check
    mask = df["EmailMatch"].isin(["", "Fail"])
    if mask.any():
        print(f"▶  (Re)checking {mask.sum()} rows with 10‑way concurrency …")
        asyncio.run(process_async(df, mask))
    else:
        print("Nothing to do – all rows already Pass.")

    target = out_path or in_path
    df.to_csv(target, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"\n✅  Saved → {target}")
    print(df["EmailMatch"].value_counts(dropna=False))

# ──────────  CLI entry‑point  ──────────
if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print(
            "Usage:\n"
            "  python email_checker.py input.csv [output.csv]\n\n"
            "If [output.csv] is omitted the input file is overwritten."
        )
        sys.exit(1)

    run_file(
        Path(sys.argv[1]),
        Path(sys.argv[2]) if len(sys.argv) == 3 else None,
    )
