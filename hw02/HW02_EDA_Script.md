# HW2: Vibe Coding EDA — Wildcat Capital Transaction Portfolio
## MIS3060 Business Intelligence with AI | Villanova University

**Due:** End of Week 5 (Wednesday 11:59 PM)
**Weight:** 5% of final grade
**Submission:** GitHub repository link submitted via Brightspace
**Tools:** Claude Cowork, Python (VS Code terminal), GitHub

---

## Overview

This assignment puts the full Week 4 workflow into practice on a real-scale wealth management dataset. Using `fact_transactions.csv` — five years of client transaction history for Wildcat Capital — you will generate an EDA script with Claude Cowork, run it in VS Code, and apply all five validation methods from this week's slides.

This assignment follows the same EDA structure you practiced in the EDA Tutorial: inspect and type-check the data, assess missing values, compute summary statistics, examine distribution shape, group and aggregate by a business dimension, and look for relationships between variables — then interpret all of it in plain business language, the way you did for the Wildcat Capital loan portfolio.

The dataset is larger than anything you have worked with before in this course: nearly 300,000 rows spanning 2,700 clients, 25 advisors, and five calendar years. Your job is not to analyze every number — it is to understand the dataset's shape, confirm it loaded correctly, characterize its key distributions and relationships, and identify anything that requires further investigation before analysis.

> *A professional analyst validates before interpreting. Every time.*

---

## Learning Objectives

- Complete a full Vibe Coding cycle: Specify → Generate → Run → Validate → Commit
- Apply all five validation methods from Week 4 to a large, multi-column dataset
- Assess distribution shape and detect relationships between variables using grouping and correlation analysis
- Distinguish intentional nulls and genuine data anomalies from data quality problems, using business context
- Produce a version-controlled deliverable with a documented validation record

---

## The Dataset

Download `fact_transactions.csv` from Brightspace. Save it to `data/raw/` in your course repository.

This file contains every client transaction recorded in Wildcat Capital's portfolio management system from January 2020 through December 2024. Each row represents one transaction event: a Buy, Sell, Deposit, Withdrawal, Dividend payment, or Advisory Fee charge.

**Known-answer benchmarks** (calculated independently — do not derive these from your script):

| Check | Expected Value |
|---|---|
| Dataset shape | 298,772 rows × 9 columns |
| Null values in `security_id` | 101,597 |
| Null values in `amount` | 0 |
| Unique values in `txn_type` | 6 |
| Count of `Buy` transactions | 83,556 |
| `txn_date` stored as | object (string) — not a date type |
| Earliest transaction date | 2020-01-01 |
| Latest transaction date | 2024-12-30 |
| Duplicate `txn_id` values | 0 |
| Mean `amount` | $54,075.17 |
| Median `amount` | $41,220.48 |
| Skewness of `amount` | 1.15 (right-skewed) |
| Correlation: `shares`–`amount` | 0.65 |
| Correlation: `price`–`amount` | 0.64 |
| Correlation: `shares`–`price` | 0.00 |
| Negative `shares` values | 836 rows (all `Buy` transactions) |

**Known grouping benchmark** — mean `amount` by `txn_type`, sorted highest to lowest:

| `txn_type` | Count | Mean `amount` | Median `amount` |
|---|---|---|---|
| Dividend | 53,864 | $64,077.30 | $48,805.60 |
| Buy | 83,556 | $63,738.49 | $47,893.58 |
| Sell | 59,755 | $63,635.55 | $48,080.16 |
| Deposit | 35,981 | $50,588.07 | $50,760.33 |
| Withdrawal | 29,850 | $49,997.34 | $49,843.42 |
| Advisory Fee | 35,766 | $7,375.17 | $859.12 |

---

## Environment Setup

Before starting Part 1, activate the virtual environment you set up earlier in the course and install this assignment's dependencies. This is the first assignment in the course that runs Python, so it's the first time you'll actually need the `.gitignore`, `requirements.txt`, and `verify_setup.py` files provided at the start of the semester — copy them into your repository root now if they aren't there already.

If you don't already have a `.venv` folder in your repository (first time working in this repo), create one:

```bash
python -m venv .venv
```

Then activate it and install dependencies:

```bash
# Windows (Command Prompt or PowerShell):
.venv\Scripts\activate

# Mac/Linux (bash/zsh):
source .venv/bin/activate

# Then, with the venv active (your prompt should show (.venv)):
pip install -r requirements.txt
python verify_setup.py
```

`verify_setup.py` checks that every required library is installed and prints its version — run it before opening Claude Cowork. If it reports anything missing, re-run `pip install -r requirements.txt` inside your activated venv.

The provided `.gitignore` already excludes your `.venv/` folder and all `.csv` files, so you do not need to add anything to it yourself for this assignment.

---

## Part 1 — EDA with Vibe Coding (50 points)

### 1A — Write Your Specification (10 points)

Before opening Claude Cowork, write a specification for your EDA script. Save it as `hw02/specification.md`.

Your specification must instruct Claude Cowork to produce **one single Python script** that performs all of the following steps in a single run:

1. Loads `data/raw/fact_transactions.csv` into a pandas DataFrame
2. Prints the shape (rows × columns)
3. Prints all column names and their data types
4. Prints the count of missing values for every column
5. Prints descriptive statistics (count, mean, std, min, 25th pct, median, 75th pct, max) for all numeric columns
6. Prints value counts and percentages for `txn_type`, sorted from most to least frequent
7. Prints the unique count of clients, advisors, and securities referenced in the file
8. Prints the earliest and latest `txn_date` (the date range of the dataset)
9. Checks for duplicate rows by `txn_id` and prints the duplicate count
10. Prints the mean, median, and skewness of the `amount` column
11. Groups the data by `txn_type` and prints, for each type, the count and the mean and median `amount` (rounded to 2 decimal places), sorted by mean amount descending
12. Computes the correlation matrix for `shares`, `price`, and `amount` (rounded to 2 decimal places), prints it, and identifies the three strongest correlations (excluding a variable's correlation with itself)
13. Prints the minimum, maximum, and count of negative values in the `shares` column, broken out by `txn_type`
14. Prints a warning if the shape is not (298772, 9)
15. Creates and saves three charts to the `hw02/charts/` folder: a histogram of `amount` with vertical lines at the mean and median, labeled clearly (`hw02/charts/hist_amount.png`); a horizontal box plot of `amount` by `txn_type` (`hw02/charts/box_amount_by_type.png`); and a scatter plot of `shares` (x-axis) vs. `amount` (y-axis) colored by `txn_type` (`hw02/charts/scatter_shares_amount.png`)
16. Saves a plain-text summary of items 2–13 to `hw02/hw02_profile.txt`
17. Includes a comment block at the top identifying the script, dataset, author, and generation date

**This is one script, not seventeen separate scripts.** All 17 items must run together in the same file, in one execution.

Write the specification in plain English. Do not write any code. The specification is your instruction to Claude Cowork — write it as clearly as if you were explaining the task to a new colleague.

**Save as:** `hw02/specification.md`

---

### 1B — Generate the Script with Claude Cowork (20 points)

Open Claude Cowork. Using your specification as your prompt, ask Claude Cowork to generate the Python EDA script.

Copy the generated script into VS Code and save it as `hw02/hw02_eda.py`. Do not modify the generated code manually unless you understand what you are changing. If something is wrong, return to Claude Cowork with a follow-up prompt describing the issue.

**What earns full credit:**
- All 17 specification items are present in the generated script
- Script runs without errors in the VS Code terminal
- Output file `hw02/hw02_profile.txt` is created
- All three chart files are created in `hw02/charts/`

**Save as:** `hw02/hw02_eda.py`

---

### 1C — Run the Script (20 points)

Run the script from the VS Code terminal:

```bash
python hw02/hw02_eda.py
```

Keep the terminal window open. You will use the full output in Part 2. Open the three saved chart files in `hw02/charts/` and keep them handy as well — you will need them in Part 2.

If the script fails, use Claude Cowork to debug it: paste the full error message and the relevant lines of code. Document the error and fix in `hw02/validation.md`.

**Note on runtime:** With nearly 300,000 rows and three charts to render, this script may take 15–45 seconds to run. This is normal. If it runs for more than two minutes, something is wrong — check with Claude Cowork.

---

## Part 2 — Validate the Results (40 points)

Apply all five validation methods from Week 4 to your EDA output. Document each of the three sections below in `hw02/validation.md` with a clearly labeled header.

---

### 2A — Known-Answer Benchmarks (8 points)

Complete this table in `hw02/validation.md`. Every row must be filled in.

| Check | Expected | Your Script Produced | Match? | Notes |
|---|---|---|---|---|
| Dataset shape | (298772, 9) | | | |
| Null count — `security_id` | 101,597 | | | |
| Null count — `amount` | 0 | | | |
| Unique `txn_type` values | 6 | | | |
| Count of `Buy` transactions | 83,556 | | | |
| `txn_date` data type | object | | | |
| Earliest `txn_date` | 2020-01-01 | | | |
| Latest `txn_date` | 2024-12-30 | | | |
| Duplicate `txn_id` count | 0 | | | |
| Mean `amount` | $54,075.17 | | | |
| Median `amount` | $41,220.48 | | | |
| Skewness of `amount` | 1.15 | | | |
| Correlation `shares`–`amount` | 0.65 | | | |
| Correlation `price`–`amount` | 0.64 | | | |
| Correlation `shares`–`price` | 0.00 | | | |
| Negative `shares` count (Buy only) | 836 | | | |
| Profile file created | Yes | | | |
| Chart files created (3) | Yes | | | |

For any row where Match = No: describe the discrepancy and paste the Claude Cowork conversation you used to investigate it.

---

### 2B — Explain the Code and Output (16 points)

Open a **new** Claude Cowork session — not the one that generated the script. In that session, send two prompts in sequence.

**Prompt 1 (the code):** Paste your complete `hw02_eda.py` script and ask:

> *"Walk me through each section of this script, including the grouping, correlation, and charting steps. What should I see in the terminal when I run it? List each expected output value explicitly."*

**Prompt 2 (the output):** Paste your complete terminal output — all lines, not just the summary numbers — and ask:

> *"Here is the terminal output from running an EDA script on a wealth management transaction dataset. What does each value mean? Flag anything that looks unexpected or that I should investigate before using this data in an analysis."*

In `hw02/validation.md`, answer:

1. Did Claude's predicted outputs (from Prompt 1) match what you actually saw in the terminal? List any discrepancies.
2. What did Claude flag as potentially unexpected or worth investigating (from Prompt 2)?
3. Did Claude mention the 101,597 null values in `security_id`? What explanation did it give?
4. Did Claude flag the `txn_date` column as a concern? Why would that matter for a time-series analysis?
5. Open your three chart files. Does what you see in each image match Claude's explanation of that section of the output? Note any differences.
6. Paste one follow-up question you asked Claude, and Claude's answer.

> *If you cannot describe what a script should produce before running it, you cannot detect when it produces the wrong answer.*

> *Start a new Claude Cowork conversation for code and output review — the session that generated the code is not a neutral reviewer.*

---

### 2C — Business Check & Cross-Validation (16 points)

**Business-reasonableness questions.** Apply your knowledge of Wildcat Capital's business. Answer each question in your own words in `hw02/validation.md` — do not paste Claude's response as your answer here.

1. `security_id`, `shares`, and `price` are all null in exactly 101,597 rows. Looking at the `txn_type` value counts, which three transaction types would you expect to have no security — and why? Do the counts add up to 101,597?
2. There are 83,556 Buy transactions and 59,755 Sell transactions. What does it mean for a wealth management firm to have significantly more Buys than Sells over a five-year period?
3. The `txn_date` column is stored as a string (type `object`) rather than a date. If Claude Cowork generated code to compute the average number of days between transactions, what would go wrong if the dates remained as strings?
4. Wildcat Capital has 2,700 clients served by 25 advisors. Is that ratio — roughly 108 clients per advisor — plausible for a registered investment advisory firm?
5. 836 `Buy` transactions have negative `shares` values (as low as −499.63), while every other transaction type in the dataset has only positive share values. What are two plausible business explanations for a negative share count on a Buy transaction (for example, a data-entry sign error versus a legitimate correction or reversal entry), and what would you do next to determine which explanation is more likely?

For any question where you are uncertain, use Claude Cowork: *"Is [observation] typical for a wealth management firm? Cite a source."*

> *You do not need to know Python to recognize that three non-trade transaction types would logically have no associated security.*

> *Investigate outliers and anomalies before deciding whether to exclude them — an unexplained pattern is a finding, not automatically an error.*

**Cross-validation.** The count of `Buy` transactions (83,556) is a central metric in any portfolio activity analysis. Verify it using two independent approaches:

- **Prompt A:** *"Write Python to count rows in fact_transactions.csv where txn_type equals exactly 'Buy'."*
- **Prompt B:** *"Write Python to count the total rows in fact_transactions.csv, then subtract the count of rows where txn_type is Sell, Deposit, Withdrawal, Dividend, or Advisory Fee."*

Run both scripts from the VS Code terminal. In `hw02/validation.md`:

6. What did each script return?
7. Do the results agree? If not, which one is wrong and why?
8. Why is it useful to verify a count using subtraction rather than direct filtering?

> *Agreement between two approaches raises confidence. Disagreement always guarantees a bug.*

---

## Part 3 — Commit and Push (10 points)

**Before committing, confirm the provided `.gitignore` is at your repository root.** `fact_transactions.csv` is 16.7 MB — too large to keep in a course repository that will accumulate homework through HW8. The `.gitignore` from the start of the course already excludes all `.csv` files and your `.venv/` folder, so no manual edits are needed — just make sure it's present (not only inside `hw02/`).

Everything you're graded on — your script, the generated profile, the charts, and your markdown deliverables — lives inside `hw02/`, so a single `git add hw02/` picks up the whole submission. The raw source file stays out of the repo entirely; graders already have independent access to `fact_transactions.csv` and don't need your copy.

Commit all deliverables with a message that documents what you found:

```bash
git add hw02/ .gitignore
git commit -m "HW2: EDA on fact_transactions — 298,772 rows confirmed, 101,597 intentional nulls explained, txn_date type flagged, 836 negative-share Buy transactions investigated"
git push origin main
```

Your commit message must describe what you learned from validation, not just what you did. Edit the example above to reflect your actual findings.

---

## Submission Checklist

- [ ] `hw02/specification.md` — 17 specific items, written before prompting Claude Cowork
- [ ] `hw02/hw02_eda.py` — runs without errors, all outputs present
- [ ] `hw02/hw02_profile.txt` — created and contains the EDA summary
- [ ] `hw02/charts/` — three chart files created (`hist_amount.png`, `box_amount_by_type.png`, `scatter_shares_amount.png`)
- [ ] `hw02/validation.md` — all three validation sections completed (covering all five Week 4 methods)
- [ ] Provided `.gitignore` and `requirements.txt` present at repo root; `verify_setup.py` run with no missing libraries
- [ ] Commit message documents findings, not just actions

**Submit:** Paste your `hw02` folder URL into Brightspace: `https://github.com/[username]/mis3060-bi-ai/tree/main/hw02`

---

## Grading Rubric

| Component | Points | What earns full credit |
|---|---|---|
| Specification (1A) | 10 | All 17 items present, written in plain English before any code |
| Generated script (1B) | 20 | All 17 outputs present, three charts created, script runs without errors |
| Run the script (1C) | 20 | Script runs without errors in VS Code, terminal output matches expected structure |
| Known-answer table (2A) | 8 | All rows filled — including distribution, correlation, and anomaly rows — mismatches investigated and documented |
| Explain the Code and Output (2B) | 16 | New session used for both prompts, discrepancies and anomalies addressed, chart images checked, follow-up question included |
| Business Check & Cross-Validation (2C) | 16 | All five business questions answered in own words with sound reasoning; both cross-validation prompts run and compared |
| Commit and Push (3) | 10 | Commit message reflects findings; raw data excluded via the provided `.gitignore` |

---

## The Bigger Picture

`fact_transactions.csv` is the central fact table in Wildcat Capital's data model. Every dashboard, report, and performance metric in this course will eventually trace back to these 298,772 rows. Understanding its structure now — what each column means, why some fields are null by design, how transaction amounts vary by type and relate to shares and price, and how the five-year date range and the negative-share anomaly fit the firm's history — will pay off in every assignment that follows.
