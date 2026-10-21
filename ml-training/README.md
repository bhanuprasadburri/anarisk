# AnaRisk URL model research workflow

This directory holds local URL data and research outputs. The raw and cleaned CSVs and model binaries are ignored by Git. The training and preparation code lives in `backend/scripts/ml` alongside AnaRisk's optional URL model inference service.

## Dataset findings

`data/malicious_phish.csv` has columns `url,type`, 651,191 rows, and four categories: benign, phishing, defacement, and malware. The reproducible preparation script maps only `benign` to 0 and the three threat categories to 1 while preserving the original category. It does not fetch URLs. See `reports/data-quality.json` for checksums and data-quality counts.

The file contains no dates, source feed, verification status, provenance statement, or license declaration. Its name, row count, and label distribution match the public [Kaggle Malicious URLs dataset](https://www.kaggle.com/datasets/sid321axn/malicious-urls-dataset), but that match does not prove this copy's origin or its usage rights. Do not publish the dataset or artifact until the applicable license is verified. Binary results cannot distinguish phishing, malware, and defacement.

Preparation retained 640,540 URLs (427,842 benign; 212,698 malicious), rejected 99 malformed URLs, removed 10,440 duplicate normalized rows, and excluded 112 normalized URLs with conflicting labels. It found 152,649 registrable-domain groups using AnaRisk's limited built-in suffix list; 4,319 groups had multiple source categories. The exact hashes and remaining counts are in `reports/data-quality.json`.

## Evaluation result

The selected model is a character 3–5-gram TF-IDF vectorizer (`max_features=300,000`) with balanced Logistic Regression. Deterministic domain-group assignment produced 452,921 training rows, 91,380 validation rows, and 96,239 test rows, with no group overlap. No chronological evaluation was possible because the source has no timestamps.

The validation threshold was 0.8578, chosen for maximum recall with validation false-positive rate at or below 1%. On the untouched grouped test set, precision was 0.962 for malicious URLs and 0.889 for benign URLs; recall was 0.755 and 0.985, respectively; F1 was 0.846, average precision 0.953, and ROC-AUC 0.971. The test confusion matrix (true rows 0/1, predicted columns 0/1) was `[[63170, 950], [7876, 24243]]`. Test false-positive rate rose to 1.48%; 7,876 malicious URLs were missed. A false positive can waste analyst time or disrupt legitimate work; a false negative can leave a malicious URL unflagged. These results are useful for research review, not sufficient to declare production readiness.

## Reproduce preparation and training (Windows PowerShell)

Run from `backend`:

```powershell
py -3.12 -m venv .venv-ml
.\.venv-ml\Scripts\Activate.ps1
python -m pip install -r ..\ml-training\requirements.txt
$env:PYTHONPATH = (Get-Location).Path
python -m scripts.ml.prepare_local_dataset `
  ..\ml-training\data\malicious_phish.csv `
  ..\ml-training\data\malicious_phish.cleaned.csv `
  ..\ml-training\reports\data-quality.json `
  --source-url https://www.kaggle.com/datasets/sid321axn/malicious-urls-dataset
python -m scripts.ml.train_local_url_model `
  ..\ml-training\data\malicious_phish.cleaned.csv `
  --artifact ..\ml-training\models\url-char-tfidf-v0.1.0-research.joblib `
  --report ..\ml-training\reports\url-char-tfidf-evaluation.json
python -m scripts.ml.predict_url "https://example.com/login" `
  --artifact ..\ml-training\models\url-char-tfidf-v0.1.0-research.joblib
```

Training assigns whole registrable-domain groups deterministically to train, validation, and test. Text vectorization is fit inside the training pipeline. The threshold is selected on validation data to maximize recall under a 1% validation false-positive-rate target; the held-out test set is evaluated only after selection. The threshold is a research operating point, not an operationally approved production threshold. Scores are not calibrated probabilities.

## AnaRisk inference integration

The versioned artifact is `models/url-char-tfidf-v0.1.0-research.joblib`. The existing authenticated `POST /api/v1/tools/url/analyze` route supports optional shadow inference through `URL_MODEL_SHADOW_ENABLED` and `URL_MODEL_ARTIFACT_PATH`. The model output is stored separately from findings and does not change the existing risk score. The current Render image does not install ML dependencies or package a model artifact. Keep shadow inference disabled until the evaluation is reviewed and a deliberate deployment artifact/dependency plan is made. No database migration is needed.

No Render or Vercel deployment was performed. Before enabling shadow inference on Render, verify rights to distribute the derived artifact, deliberately package the matching scikit-learn/joblib runtime and model into the backend build, set `URL_MODEL_ARTIFACT_PATH` to that packaged path, and then set `URL_MODEL_SHADOW_ENABLED=true`. The repository's present Render Blueprint leaves the feature at its default-off setting. Vercel requires no configuration change; the existing URL investigation API client is unchanged.

The model is research-only. The dataset has no collection dates, its license/provenance are unresolved, the built-in registrable-domain helper uses a limited suffix list, and current results would not establish performance on newer URLs.

## Audit and model comparison

The saved artifact's metadata and the evaluation report were checked against the cleaned-data SHA-256 and independently reconstructed deterministic domain split. The saved artifact reproduced the validation and test metrics exactly. No train/validation/test registrable-domain group overlap was found. The validation threshold (0.8578006) is chosen by maximum validation recall with validation false-positive rate at or below 1%; no test scores enter that choice. The test false-positive rate is higher (1.48%).

An aggregate-only error analysis is in `reports/url-char-tfidf-error-analysis.json`; it contains no URL, host, domain, or row identifiers. Of 32,119 malicious held-out URLs, 7,876 were false negatives and 950 of 64,120 benign URLs were false positives. False-negative rates differed by source label: phishing 48.6% (6,823/14,051), malware 16.1% (619/3,841), and defacement 3.1% (434/14,227). Higher false-negative rates also appeared for HTTPS URLs (55.3% vs 6.1% for non-HTTPS) and percent-encoded URLs (79.3% vs 23.1% without encoding), though these are associations in this dataset, not causes. Exact normalized URL conflicts were excluded during preparation; repeated domains with mixed categories remain a possible label-noise/source-mixing signal. The CSV has no timestamps, so stale examples cannot be identified.

`reports/url-model-comparison.json` records a predeclared comparison with character TF-IDF plus Multinomial Naive Bayes. It was worse on validation average precision (0.923 vs 0.958) and malicious recall at the same validation FPR constraint (0.511 vs 0.724), so it was not selected and no new model artifact was saved. Its held-out results are reported for transparency only: AP 0.908, ROC-AUC 0.938, malicious precision 0.964, recall 0.495, F1 0.654, FPR 0.92%, and 16,210 false negatives. The original artifact remains intact.

The data-quality report checksum and class counts match the local CSV, and they match the counts published for the [Kaggle dataset listing](https://www.kaggle.com/datasets/sid321axn/malicious-urls-dataset). That is not proof that this copy came from that listing or that the underlying data may be redistributed. The local license is unset and the Kaggle listing's terms could not be verified in this audit; source rights remain unresolved. No independent, recent dataset with verified labels, timestamps, and a compatible license was available locally, so fresh independently sourced data is needed before staging evaluation can establish current performance.

Reproduce the audit from `backend` after installing the ML requirements:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m scripts.ml.audit_and_compare_url_model `
  ..\ml-training\data\malicious_phish.csv `
  ..\ml-training\data\malicious_phish.cleaned.csv `
  ..\ml-training\models\url-char-tfidf-v0.1.0-research.joblib `
  ..\ml-training\reports\url-char-tfidf-evaluation.json `
  ..\ml-training\reports\data-quality.json `
  ..\ml-training\reports\url-char-tfidf-error-analysis.json `
  ..\ml-training\reports\url-model-comparison.json `
  ..\ml-training\models\url-char-tfidf-mnb-v0.1.1-research.joblib
```

## Second dataset experiment: Training.parquet and Testing.parquet

The two Parquet inputs contain 7,658 and 3,772 rows, respectively, with a shared 89-column schema and balanced `legitimate`/`phishing` labels. Their original split is not independent: 636 registrable domains and 8 normalized URLs occur in both files. The preparation workflow combines the files, removes 14 duplicate normalized rows, and deterministically reassigns registrable-domain groups to train, validation, and test. It uses only the URL string and maps `legitimate` to 0 and `phishing` to 1. The other 87 columns—including page, DNS, popularity, and external-report features—are excluded because they are not available to AnaRisk's URL-only inference path. No URLs are fetched. See `reports/phishing_url_pair-quality.json` for source checksums and detailed quality counts.

This pair also has no embedded provenance, license, or collection timestamps. The source split is therefore not treated as a clean held-out evaluation, and the derived data/model should not be redistributed until source rights are verified.

The same character TF-IDF/Logistic Regression baseline trained on 7,438 rows and used 1,980 validation rows plus 1,998 grouped test rows. At the validation-selected threshold (0.7686), test malicious precision was 0.835 and recall was 0.586; benign precision was 0.692 and recall was 0.889. F1 was 0.689, average precision 0.872, ROC-AUC 0.896, and the test confusion matrix was `[[909, 113], [404, 572]]`. The validation false-positive rate target was 1%, but the test false-positive rate was 11.1%; 404 phishing URLs were missed. This generalization gap makes the model unsuitable for replacing or enabling the existing model.

Reproduce from `backend` after installing `ml-training/requirements.txt`:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m scripts.ml.prepare_parquet_url_dataset `
  ..\ml-training\data `
  ..\ml-training\data\phishing_url_pair.cleaned.csv `
  ..\ml-training\reports\phishing_url_pair-quality.json
python -m scripts.ml.train_local_url_model `
  ..\ml-training\data\phishing_url_pair.cleaned.csv `
  --artifact ..\ml-training\models\url-char-tfidf-parquet-v0.1.0-research.joblib `
  --report ..\ml-training\reports\phishing_url_pair-evaluation.json
python -m scripts.ml.predict_url "https://example.com/login" `
  --artifact ..\ml-training\models\url-char-tfidf-parquet-v0.1.0-research.joblib
```
