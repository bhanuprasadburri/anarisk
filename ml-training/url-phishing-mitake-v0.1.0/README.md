# Mitake URL phishing model — v0.1.0 research

This is an offline research workflow isolated from AnaRisk production and staging. It does not change the existing URL model, API, risk score, threshold, or shadow-inference settings. Never use the artifact as a production verdict or distribute it.

## Dataset and rights record

- Dataset listing: [Mitake/PhishingURLsANDBenignURLs](https://huggingface.co/datasets/Mitake/PhishingURLsANDBenignURLs)
- Local input: `../data/PhishBenignDataset.csv`; expected columns `url,label`.
- The hosted card lists 886,181 rows, 42.9 MB, CSV, and CC BY-SA 4.0. Its README is empty and it does not explain integer labels.
- For this experiment, the user confirmed `0 = benign`, `1 = phishing` on 2026-10-21. Do not describe that mapping as documented by the dataset publisher.
- This local file's exact revision and checksum have not been verified against the hosted repository. The card's license declaration is recorded, but upstream rights and whether a model artifact is a share-alike adaptation have not received legal review.
- Research use is private and local only. No dataset or model distribution, commercial deployment, containerization, staging, or production use is authorized by this workflow.
- Source labels are not independently verified. There are no timestamps or source IDs. No URL is opened, fetched, resolved, or rendered.

The current audit reports a large intersection with the old URL source dataset (normalized URL and registrable-domain hashes). This candidate must not be called an independent source-level benchmark. Domain-separated candidate test results are held out from the new model's training, but the source-level overlap limits generalization claims and invalidates a clean comparison to the old model on this test.

## Workflow

Install the pinned requirements into the repository's `backend/.venv-ml` environment, then run these commands from the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$(Get-Location)\backend;$(Get-Location)\ml-training\url-phishing-mitake-v0.1.0"
$Python = ".\backend\.venv-ml\Scripts\python.exe"
$Data = "$(Get-Location)\ml-training\data\PhishBenignDataset.csv"
$Experiment = "$(Get-Location)\ml-training\url-phishing-mitake-v0.1.0"

& $Python "$Experiment\prepare.py" $Data `
  --output "$Experiment\data\prepared.csv" `
  --reference "$(Get-Location)\ml-training\data\malicious_phish.csv"

$PreparedHash = (Get-FileHash "$Experiment\data\prepared.csv" -Algorithm SHA256).Hash.ToLower()
$Model = "$Experiment\models\url-char-tfidf-mitake-v0.1.0-research-$($PreparedHash.Substring(0,8)).joblib"

& $Python "$Experiment\train.py" "$Experiment\data\prepared.csv" `
  --artifact $Model `
  --report "$Experiment\reports\training.json"

& $Python "$Experiment\evaluate.py" "$Experiment\data\prepared.csv" $Model `
  --report "$Experiment\reports\evaluation.json"

& $Python "$Experiment\predict.py" "https://example.com/" --artifact $Model
& $Python -m pytest "$Experiment\tests" -q
& $Python -m pytest backend\tests\test_ml_dataset_preparation.py backend\tests\test_ml_model_audit.py backend\tests\test_ml_research_pipeline.py backend\tests\test_url_model_inference.py -q
```

Install dependencies with `& .\backend\.venv-ml\Scripts\python.exe -m pip install -r ml-training/url-phishing-mitake-v0.1.0/requirements.txt`. `tldextract` is pinned and configured to use its packaged Public Suffix List snapshot without fetching it. Data and model binaries are ignored by this experiment's `.gitignore`; reports and source code contain no raw URL values.

## Preparation and evaluation rules

- The source CSV is preserved. Preparation uses AnaRisk's existing URL normalizer, retains only normalized `url`, mapped `label`, and a SHA-256 registrable-domain group key in its local prepared data. It never logs raw URLs. The original remains available at the input path.
- Empty, unknown-label, malformed, and normalized-label-conflict rows are counted and excluded. Repeated normalized URLs with the same label are deduplicated. URLs are normalized for consistent model/inference behavior; counts of changed strings are reported. This is not a claim that the source form is invalid.
- All subdomains of a registrable domain use one PSL-derived group. Group hashes are assigned deterministically to train/validation/test at 70/15/15. Reports contain only counts and hashes, not domains.
- Character TF-IDF (3–5 grams, `min_df=2`, at most 300,000 features, float32) is fit on training data. Logistic Regression and Multinomial Naive Bayes use identical partitions. Selection uses validation recall at validation FPR <=1%, with AP as the tie-break; test is untouched until evaluation.
- Evaluation checks domain and normalized URL disjointness. It reports phishing precision/recall/F1, specificity, balanced accuracy, per-class metrics, confusion matrix, FPR/FNR, AP, ROC-AUC, inference throughput, model size, and peak process memory when the OS exposes it.
- Historical baseline metrics use a different dataset and the old positive label also includes malware and defacement. Due the source overlap recorded in the audit, no direct baseline comparison is claimed.

## Output and remaining limits

`data-quality.json` and `provenance-manifest.json` record dataset hash, row counts, duplicate/conflict decisions, label mapping basis, source/license declaration, and limitations. `training.json` contains configuration and validation model-selection details. `evaluation.json`, model card, and artifact checksum are created only by local runs. Dataset and model output stay local and ignored. Before any staging review, obtain rights review covering upstream data, model-weight treatment, intended hosting, and use; then authorize a separate staging task. Existing `-RightsReviewed` safeguards remain in force.
