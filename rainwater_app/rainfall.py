from __future__ import annotations

from io import BytesIO

import pandas as pd


def load_rainfall_csv(file_bytes: bytes) -> pd.DataFrame:
    """Load rainfall CSV containing Date and Precipitation columns."""
    if not file_bytes:
        raise ValueError("Rainfall file is empty.")

    df = pd.read_csv(BytesIO(file_bytes))

    normalized = {c.lower().strip(): c for c in df.columns}
    required = {"date", "precipitation"}
    if not required.issubset(set(normalized.keys())):
        raise ValueError("CSV must include Date and Precipitation columns.")

    result = df[[normalized["date"], normalized["precipitation"]]].copy()
    result.columns = ["Date", "Precipitation"]
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["Precipitation"] = pd.to_numeric(result["Precipitation"], errors="coerce")
    result = result.dropna(subset=["Date"]).fillna({"Precipitation": 0.0})
    result = result.sort_values("Date").reset_index(drop=True)

    if result.empty:
        raise ValueError("No valid rows found after parsing Date/Precipitation.")

    return result
