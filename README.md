# Spending Dashboard (Public Edition)

Executive-friendly personal spending insights powered by Python notebooks and (optionally) Plaid + Azure OpenAI.  
This public edition includes **sample data** so anyone can run it **without secrets**.

---

## What it does

- **Consolidates** transactions (sample mode included; Plaid optional).
- **Enriches** merchants/categories using a small mapping layer.
- **Summarizes** weekly/monthly spend with clear, exec-ready outputs.
- **Optional**: email/PDF generation for weekly digests (disabled by default).

---

## Architecture (high level)

- **Data layer**: CSV/Parquet in data/ (gitignored); sample data in data/sample/.
- **Orchestration**: lightweight via notebooks and a manual GitHub Action smoke test.
- **Enrichment**: merchant/category mapping (dim CSV); optional model-based enrichment.
- **Outputs**: summaries, charts, and dashboard tiles/screenshots in /docs.

**Flow:** Plaid (optional) → Build (raw) → Enrich & Insights → (optional) Email/PDF  
*(This repo publishes code + sample data only; your personal data stays local.)*

---

## Repo layout

config/
sample/
merchants_dim.sample.csv
data/
sample/
transactions_sample.csv
docs/
screenshot-powerbi.png # replace with real screenshot
email-preview.png # replace with real screenshot
.github/
workflows/
pull-transactions.yml # manual-only, safe smoke test
scripts/
build_latest.ipynb # optional (Plaid)
enrich_transactions.ipynb
.env.example # placeholders only (safe)
.gitignore


---

## Quickstart (Sample Data, No Secrets)

**Requirements**
- Python 3.10+
- pip install -r requirements.txt (if present)

**Run**
1. Open scripts/enrich_transactions.ipynb.
2. Ensure it points at the sample file: data/sample/transactions_sample.csv.  
   *(If you have not added a Parameters cell, set the input path in the first cell where the CSV is read.)*
3. Run all cells. Outputs (summaries/charts) are written to data/processed/ (gitignored).

**You’ll see**
- Clean sample transactions
- Category enrichment via config/sample/merchants_dim.sample.csv
- Example weekly/monthly rollups and example charts

> Tip: Replace the placeholder images in /docs with your own screenshots.

---

## Full pipeline (Plaid + Azure + optional Email/PDF) — local only

1. Copy .env.example → .env, then fill real values locally:
   - PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV, PLAID_ACCESS_TOKENS
   - AZURE_OPENAI_* (if using embeddings or model-based enrichment)
   - Leave EMAIL_ENABLED=0, PDF_ENABLED=0 until you are ready.
2. Run scripts/build_latest.ipynb to pull fresh transactions to data/raw/.
3. Run scripts/enrich_transactions.ipynb for enrichment and insights.
4. When ready to test email/PDF locally, toggle:
   - EMAIL_ENABLED=1 and/or PDF_ENABLED=1 **in your .env only** (never in CI).

**Safety defaults**
- CI workflow is **manual-only** and **never** sends email/PDF.
- data/raw/ and data/processed/ are gitignored.
- Secrets belong in .env (gitignored) or GitHub Actions **Secrets**.

---

## CI (public-safe)

A single manual workflow at .github/workflows/pull-transactions.yml:
- Verifies sample dataset exists.
- Prints safety flags.
- Does **not** execute anything that requires secrets or sends email/PDF.

---

## Screenshots

- Power BI tiles: docs/screenshot-powerbi.png
- Email preview: docs/email-preview.png

*(Replace placeholders with real images for your portfolio.)*

---

## License

This project is open-sourced under the **MIT License** (see LICENSE).

---

## Attribution / Contact

Built by Koise — analytics + automation. Feedback and suggestions welcome.
