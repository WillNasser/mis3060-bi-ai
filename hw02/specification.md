# EDA Script Specification — Wildcat Capital Transaction Data (HW02)

Write me a single, cohesive Python program that performs all of the following steps in one run:

1. Loads `data/raw/fact_transactions.csv` into a pandas DataFrame
2. Prints the shape (rows × columns)
3. Prints all column names and their data types
4. Prints the count of missing values for every column
5. Prints descriptive statistics (count, mean, std, min, 25th percentile, median, 75th percentile, max) for all numeric columns
6. Prints value counts and percentages for `txn_type`, sorted from most to least frequent
7. Prints the unique count of clients, advisors, and securities referenced in the file
8. Prints the earliest and latest `txn_date` (the date range of the dataset)
9. Checks for duplicate rows by `txn_id` and prints the duplicate count
10. Prints the mean, median, and skewness of the `amount` column
11. Groups the data by `txn_type` and prints, for each type, the count and the mean and median `amount` (rounded to 2 decimal places), sorted by mean amount descending
12. Computes the correlation matrix for `shares`, `price`, and `amount` (rounded to 2 decimal places), prints it, and identifies the three strongest correlations (excluding a variable's correlation with itself)
13. Prints the minimum, maximum, and count of negative values in the `shares` column, broken out by `txn_type`
14. Prints a warning if the shape is not (298772, 9)
15. Creates and saves three charts to the `hw02/charts/` folder:
    - A histogram of `amount` with vertical lines at the mean and median, labeled clearly, saved as `hw02/charts/hist_amount.png`
    - A horizontal box plot of `amount` by `txn_type`, saved as `hw02/charts/box_amount_by_type.png`
    - A scatter plot of `shares` (x-axis) vs. `amount` (y-axis), colored by `txn_type`, saved as `hw02/charts/scatter_shares_amount.png`
16. Saves a plain-text summary of items 2–13 to `hw02/hw02_profile.txt`
17. Includes a comment block at the top identifying the script, dataset, author, and generation date

**This is one script, not seventeen separate scripts.** All 17 items must run together in the same file, in a single execution.
