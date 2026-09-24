"""
hw02_eda.py

Exploratory Data Analysis Script -- Wildcat Capital Transaction Portfolio
Dataset:    data/raw/fact_transactions.csv
Author:     <Your Name>
Course:     MIS3060 Business Intelligence with AI, Villanova University
Generated:  2026-09-23

Performs a full EDA pass on Wildcat Capital's fact_transactions dataset:
loads the data, profiles its shape/types/missingness, computes descriptive
statistics, groups and correlates key numeric fields, flags anomalies, and
saves both a plain-text summary and three diagnostic charts.

Run from the repository root:
    python hw02/hw02_eda.py
"""

from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Paths (relative to the repository root)
# ---------------------------------------------------------------------------
DATA_PATH = Path("data/raw/fact_transactions.csv")
CHARTS_DIR = Path("hw02/charts")
PROFILE_PATH = Path("hw02/hw02_profile.txt")
EXPECTED_SHAPE = (298772, 9)

CHARTS_DIR.mkdir(parents=True, exist_ok=True)

profile_lines = []


def log(text=""):
    """Print to the console and capture the same line for the profile file."""
    print(text)
    profile_lines.append(str(text))


# ---------------------------------------------------------------------------
# 1. Load the data
# ---------------------------------------------------------------------------
df = pd.read_csv(DATA_PATH)

# ---------------------------------------------------------------------------
# 2. Shape
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 2 - DATASET SHAPE")
log("=" * 70)
log(f"Rows: {df.shape[0]:,} | Columns: {df.shape[1]}")
log("")

# ---------------------------------------------------------------------------
# 3. Column names and data types
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 3 - COLUMN NAMES AND DATA TYPES")
log("=" * 70)
log(df.dtypes.to_string())
log("")

# ---------------------------------------------------------------------------
# 4. Missing values per column
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 4 - MISSING VALUES PER COLUMN")
log("=" * 70)
log(df.isnull().sum().to_string())
log("")

# ---------------------------------------------------------------------------
# 5. Descriptive statistics (numeric columns)
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 5 - DESCRIPTIVE STATISTICS (numeric columns)")
log("=" * 70)
log(df.describe().round(2).to_string())
log("")

# ---------------------------------------------------------------------------
# 6. txn_type value counts and percentages
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 6 - TXN_TYPE VALUE COUNTS (most to least frequent)")
log("=" * 70)
type_counts = df["txn_type"].value_counts()
type_pct = (df["txn_type"].value_counts(normalize=True) * 100).round(2)
type_summary = pd.DataFrame({"count": type_counts, "pct_of_total": type_pct})
log(type_summary.to_string())
log("")

# ---------------------------------------------------------------------------
# 7. Unique entity counts
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 7 - UNIQUE ENTITY COUNTS")
log("=" * 70)
log(f"Unique clients:    {df['client_id'].nunique():,}")
log(f"Unique advisors:   {df['advisor_id'].nunique():,}")
log(f"Unique securities: {df['security_id'].nunique():,}")
log("")

# ---------------------------------------------------------------------------
# 8. Transaction date range
#    (txn_date is stored as a string/object, not a real date type --
#     it is parsed here only to compute the min/max, not mutated in df)
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 8 - TRANSACTION DATE RANGE")
log("=" * 70)
txn_dates = pd.to_datetime(df["txn_date"])
log(f"Earliest txn_date: {txn_dates.min().date()}")
log(f"Latest txn_date:   {txn_dates.max().date()}")
log("")

# ---------------------------------------------------------------------------
# 9. Duplicate txn_id check
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 9 - DUPLICATE TXN_ID CHECK")
log("=" * 70)
dup_count = df["txn_id"].duplicated().sum()
log(f"Duplicate txn_id rows: {dup_count}")
log("")

# ---------------------------------------------------------------------------
# 10. amount: mean, median, skewness
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 10 - AMOUNT: MEAN / MEDIAN / SKEWNESS")
log("=" * 70)
amount_mean = df["amount"].mean()
amount_median = df["amount"].median()
amount_skew = df["amount"].skew()
log(f"Mean amount:   ${amount_mean:,.2f}")
log(f"Median amount: ${amount_median:,.2f}")
log(f"Skewness:      {amount_skew:.2f}")
log("")

# ---------------------------------------------------------------------------
# 11. Group by txn_type: count, mean, median amount (sorted by mean desc)
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 11 - AMOUNT BY TXN_TYPE (count, mean, median)")
log("=" * 70)
group_summary = (
    df.groupby("txn_type")["amount"]
    .agg(count="count", mean_amount="mean", median_amount="median")
    .round(2)
    .sort_values("mean_amount", ascending=False)
)
log(group_summary.to_string())
log("")

# ---------------------------------------------------------------------------
# 12. Correlation matrix for shares, price, amount + top 3 strongest pairs
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 12 - CORRELATION MATRIX (shares, price, amount)")
log("=" * 70)
corr = df[["shares", "price", "amount"]].corr().round(2)
log(corr.to_string())
log("")

pairs = [(a, b, corr.loc[a, b]) for a, b in combinations(corr.columns, 2)]
pairs_sorted = sorted(pairs, key=lambda p: abs(p[2]), reverse=True)
log("Three strongest correlations (excluding self-correlation):")
for a, b, val in pairs_sorted[:3]:
    log(f"  {a} <-> {b}: {val:.2f}")
log("")

# ---------------------------------------------------------------------------
# 13. shares: min, max, negative count -- broken out by txn_type
# ---------------------------------------------------------------------------
log("=" * 70)
log("ITEM 13 - SHARES: MIN / MAX / NEGATIVE COUNT BY TXN_TYPE")
log("=" * 70)
shares_summary = df.groupby("txn_type")["shares"].agg(
    min_shares="min",
    max_shares="max",
    negative_count=lambda s: (s < 0).sum(),
)
log(shares_summary.to_string())
log("")

# ---------------------------------------------------------------------------
# 14. Shape warning (console only -- not part of the saved profile)
# ---------------------------------------------------------------------------
if df.shape != EXPECTED_SHAPE:
    print(f"WARNING: expected shape {EXPECTED_SHAPE}, but got {df.shape}.")
else:
    print(f"Shape check passed: {df.shape} matches expected {EXPECTED_SHAPE}.")

# ---------------------------------------------------------------------------
# 15. Charts -- saved to hw02/charts/
# ---------------------------------------------------------------------------
# 15a. Histogram of amount, with mean/median lines
fig, ax = plt.subplots(figsize=(10, 6))
ax.hist(df["amount"], bins=50, color="#4C72B0", edgecolor="white")
ax.axvline(amount_mean, color="red", linestyle="--", linewidth=2,
           label=f"Mean: ${amount_mean:,.2f}")
ax.axvline(amount_median, color="green", linestyle="--", linewidth=2,
           label=f"Median: ${amount_median:,.2f}")
ax.set_title("Distribution of Transaction Amount", fontsize=14, fontweight="bold")
ax.set_xlabel("Amount ($)")
ax.set_ylabel("Frequency")
ax.legend()
fig.tight_layout()
fig.savefig(CHARTS_DIR / "hist_amount.png", dpi=150)
plt.close(fig)

# 15b. Horizontal box plot of amount by txn_type
fig, ax = plt.subplots(figsize=(10, 6))
order = df.groupby("txn_type")["amount"].median().sort_values(ascending=False).index
data_by_type = [df.loc[df["txn_type"] == t, "amount"] for t in order]
try:
    # matplotlib >= 3.9 renamed this parameter to tick_labels
    ax.boxplot(data_by_type, vert=False, tick_labels=list(order))
except TypeError:
    ax.boxplot(data_by_type, vert=False, labels=list(order))
ax.set_title("Amount Distribution by Transaction Type", fontsize=14, fontweight="bold")
ax.set_xlabel("Amount ($)")
fig.tight_layout()
fig.savefig(CHARTS_DIR / "box_amount_by_type.png", dpi=150)
plt.close(fig)

# 15c. Scatter plot of shares vs. amount, colored by txn_type
fig, ax = plt.subplots(figsize=(10, 6))
types = df["txn_type"].unique()
colors = plt.cm.tab10(np.linspace(0, 1, len(types)))
for t, c in zip(types, colors):
    subset = df[df["txn_type"] == t]
    ax.scatter(subset["shares"], subset["amount"], s=8, alpha=0.4, color=c, label=t)
ax.set_title("Shares vs. Amount by Transaction Type", fontsize=14, fontweight="bold")
ax.set_xlabel("Shares")
ax.set_ylabel("Amount ($)")
ax.legend(markerscale=3)
fig.tight_layout()
fig.savefig(CHARTS_DIR / "scatter_shares_amount.png", dpi=150)
plt.close(fig)

print(f"Charts saved to {CHARTS_DIR}/")

# ---------------------------------------------------------------------------
# 16. Save plain-text summary of items 2-13 to hw02/hw02_profile.txt
# ---------------------------------------------------------------------------
with open(PROFILE_PATH, "w") as f:
    f.write("\n".join(profile_lines))

print(f"Profile summary saved to {PROFILE_PATH}")
