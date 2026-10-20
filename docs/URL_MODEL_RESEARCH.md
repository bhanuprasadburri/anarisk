# Offline phishing URL research pipeline

This is an **offline research tool**, not the production AnaRisk detector. It does not fetch submitted URLs, render HTML, load pages, or alter production risk scores. Dataset indicators and model artifacts must remain outside Git.

## Source selected

The candidate source is [PhreshPhish](https://huggingface.co/datasets/phreshphish/phreshphish), a historical phishing webpage dataset whose card lists URL, `phish`/`benign` label, target, date, language, and HTML fields. The card states CC BY 4.0, anti-phishing research use, and a 36.6 GB full size. The pipeline consumes only URL, label, and date. It ignores HTML and never opens URLs. Pin and record the exact source revision and source split when downloading data. Do not redistribute source rows in Git.

No dataset is included or downloaded in this repository. No model has been trained, and no evaluation metrics are available yet. A PhreshPhish URL-only lexical classifier would not be website-content analysis and its score would not be calibrated probability of harm.

## Preparation

Install the optional tools in a dedicated research environment, not the Render API image:

```powershell
cd backend
python -m pip install -r requirements-ml.txt
```

Obtain the official train and test Parquet files using the dataset host's documented method. Store them outside the repository or under the ignored `backend/var/datasets/`. The complete source is large; check available disk and memory first. The preparer streams Parquet in bounded batches and reads only URL/label/date columns. Dataset downloads are a separate operator action; never fetch any URL value from a row.

```powershell
python -m scripts.ml.url_dataset var/datasets/phreshphish-train.parquet var/datasets/train.csv --source-split train --source-revision <40-character-commit-sha>
python -m scripts.ml.url_dataset var/datasets/phreshphish-test.parquet var/datasets/test.csv --source-split test --source-revision <40-character-commit-sha>
python -m scripts.ml.train_url_model var/datasets/train.csv var/datasets/test.csv
```

Preparation writes a manifest beside each output with source attribution, pinned revision, input/output SHA-256, optional operator-supplied retrieval time, source date range, class counts, invalid/unknown/duplicate counts, normalization, and safety limitations. Retrieval time is recorded as unknown if it is not supplied. The trainer compares logistic regression, random forest, and histogram gradient boosting; selects by validation PR-AUC; holds out the source's official test split; rejects hostname overlap across train/validation/test; selects the classification threshold on validation only; and writes a JSON report plus an ignored joblib artifact.

## Deployment gate

Do not deploy this artifact into risk scoring until the report has been reviewed for source revision, label quality, date range, class balance, split isolation, false positives/negatives, temporal shift, calibration, resource use, and the app's intended inputs. The present application has no production model loader for this research artifact. Keep model output, indicator matches, heuristic signals, and analyst conclusions separate. Missing matches never mean safe.
