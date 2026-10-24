# Local dataset models

This workflow uses local, ignored data under `ml-training/data`. It never fetches URLs or sends data to an external service. Prepared data, reports, and serialized models stay local and are ignored by Git.

## Inputs and decisions

| File | Audited schema | Use |
| --- | --- | --- |
| `Dataset.csv` | 116,600 rows; 26 columns; labels 0=benign and 1=phishing | URL character TF-IDF model. URL text is the model input; the 22 numeric columns are validated and reported but not used by this model. `url`, `dom`, and `tld` are never model inputs. |
| `spambase.data` + `spambase.names` | 4,601 rows; 57 numeric features plus binary target | Offline model requiring the original 57 feature vector. This is a spam model, not a phishing model, and it does not accept raw email text. |
| `top-1m.csv` | 1,000,000 rank/domain pairs, no header | Audit-only. No release ID or checksum from the publisher accompanies the local file, and domain names alone are not URL examples. It is not used to assign benign labels. |

The URL-Phish publisher describes 100,000 benign and 11,660 phishing URLs, while the local file has 100,000 and 16,600 respectively. Its schema and labels match the listing, but that row-count discrepancy means the exact local revision is unverified. The publisher lists CC BY 4.0. [Dataset listing](https://data.mendeley.com/datasets/65z9twcx3r/1)

The Spambase file matches the UCI repository's 4,601-row, 57-feature dataset. UCI describes label 1 as unsolicited commercial email (spam), and lists CC BY 4.0. Its age and collection-specific indicators limit present-day transfer. [UCI Spambase](https://archive.ics.uci.edu/dataset/94/spambase)

The local Tranco-like list has no permanent list ID or provenance manifest. Tranco recommends citing a permanent list reference for reproducibility. [Tranco](https://tranco-list.eu/)

## Reproduce

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = (Get-Location).Path + '\backend'
$Python = '.\backend\.venv-ml\Scripts\python.exe'

& $Python -m pip install -r backend\requirements-ml.txt
& $Python ml-training\url-phish\prepare_dataset.py `
  ml-training\data\Dataset.csv `
  ml-training\data\urlphish-prepared.csv `
  ml-training\reports\urlphish-preparation.json
& $Python backend\scripts\ml\train_local_url_model.py `
  ml-training\data\urlphish-prepared.csv `
  --artifact ml-training\models\urlphish-char-tfidf-v0.1-research.joblib `
  --report ml-training\reports\urlphish-evaluation.json
& $Python ml-training\train_spambase.py `
  ml-training\data\spambase.data `
  ml-training\data\spambase.names `
  ml-training\models\spambase-logreg-v1-research.joblib `
  ml-training\reports\spambase-evaluation.json
```

Run the Spambase contract tests in the isolated ML environment:

```powershell
$env:PYTHONPATH = (Get-Location).Path + '\ml-training'
& $Python -m pytest --confcutdir=ml-training\tests ml-training\tests\test_spambase_model.py -q
```

## Results from the local run

URL-Phish preparation retained 115,076 normalized URL rows from 116,600 source rows, removed 1,524 repeated normalized URLs, found 14 missing `tld` cells, and found no conflicting normalized labels. The 22 numeric features were checked for numeric validity and excluded from model input. A deterministic 70/15/15 registrable-domain split trained a character 3–5-gram TF-IDF and balanced Logistic Regression model. At the validation-selected threshold 0.5051, held-out test phishing precision was 91.6%, recall 91.3%, F1 91.5%, false-positive rate 0.79%, average precision 0.9729, and ROC-AUC 0.9962. The test confusion matrix (true labels 0/1, predicted columns 0/1) was `[[14477, 115], [120, 1261]]`. The report also records the limited suffix-list grouping limitation.

Spambase excluded 6 rows in 3 exact feature-vector groups whose identical vectors had contradictory labels, then split the remaining 4,595 rows by feature-vector hash so exact repeats stayed together. At the validation-selected threshold 0.9929, held-out spam precision was 94.3%, recall 36.8%, F1 52.9%, false-positive rate 1.37%, average precision 0.9295, and ROC-AUC 0.9615. The test confusion matrix was `[[432, 6], [172, 100]]`. The validation target was FPR <=1%; test FPR can differ and did. The high threshold misses many spam messages by design under this constraint.

Reports include hashes, split counts, selected thresholds, metrics, and dependency versions. Model scores are uncalibrated and must not be interpreted as probabilities.

## AnaRisk inference integration

The URL artifact follows `char-tfidf-url-v1`, which the existing `app.services.url_model` shadow inference already accepts. To opt into local shadow scoring, configure `URL_MODEL_SHADOW_ENABLED=true` and `URL_MODEL_ARTIFACT_PATH` to the local artifact path for the backend process. Shadow output is metadata and does not alter findings, risk scores, or verdicts. The default remains disabled; do not enable it for deployment review without a separate evaluation and rights review.

Spambase is exposed only through `predict_spambase(features, artifact_path)` in `ml-training/spambase_model.py`. It validates a 57-number vector and returns the source target name `spam`; the production email analyzer receives raw text and there is no validated, compatible extractor for the historical Spambase features. It is therefore not connected to raw email analysis.

No model binaries or raw/prepared datasets should be committed. Local output paths are covered by `.gitignore`.
