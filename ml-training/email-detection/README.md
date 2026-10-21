# Email phishing research baseline

This isolated workflow does not modify AnaRisk's FastAPI email analysis, findings, risk score, deployment settings, database, or frontend. It trains and runs offline only.

## Dataset audit

The local input used for this experiment is `../data/phishing_email.csv`. It has 82,486 rows and columns `text_combined,label`; label 0 has 39,595 rows and label 1 has 42,891. These schema/counts match the published [Kaggle Phishing Email Dataset card](https://www.kaggle.com/datasets/naserabdullahalam/phishing-email-dataset), whose metadata reports CC BY-SA 4.0. The local copy has no version/checksum manifest that proves it came from that release. Its constituent corpora may also have separate terms, so do not redistribute the input or derived model before attribution, source rights, and privacy review.

The source card describes the positive class as spam/phishing. That is a useful research proxy, but spam detection does not establish phishing detection: the class can include unsolicited bulk email that is not credential theft, impersonation, or another phishing attempt. No local message content is copied into audit/evaluation reports.

The audit found one missing message, 408 repeated rows across 407 case/whitespace-normalized text groups, and zero duplicate text groups with conflicting labels. Preparation drops the missing message, keeps one copy of identical normalized messages, and excludes every text group if labels conflict. The longest message is 4,279,526 characters; three rows are truncated to 200,000 characters. No sender, campaign, thread, or source-ID columns exist. The file has no dedicated timestamp column, so neither source-based nor temporal holdout can be guaranteed. Near duplicates and source/corpus leakage remain possible.

## Reproduce

From the repository root, install the isolated pinned dependencies and audit/train:

```powershell
python -m venv .venv-email
.\.venv-email\Scripts\Activate.ps1
python -m pip install -r ml-training\email-detection\requirements.txt
python ml-training\email-detection\audit_dataset.py `
  ml-training\data\phishing_email.csv `
  --report ml-training\email-detection\reports\dataset-audit.json
python ml-training\email-detection\train_model.py `
  ml-training\data\phishing_email.csv
```

The artifact filename and model version include the source CSV hash and are created under `email-detection/models/`. Evaluation metadata is written under `email-detection/reports/`. Both are ignored where appropriate; the aggregate reports contain no message contents.

The baseline masks email addresses, URLs, and IPv4 strings; applies NFKC and whitespace normalization; then fits word 1–2 gram TF-IDF (up to 120,000 features) plus class-balanced Logistic Regression. The deterministic 70/15/15 split hashes normalized full-message text, so repeated exact text cannot cross partitions. TF-IDF is fit on training only. The threshold maximizes validation recall subject to validation FPR <=1%; the final test set is evaluated only after that choice. This is a random message-group holdout, not a source-, campaign-, sender-, or time-separated estimate.

## Current local result

Artifact: `models/email-tfidf-logreg-v0.1.0-research-73a5c541.joblib`  
Report: `reports/email-tfidf-logreg-v0.1.0-research-73a5c541-evaluation.json`

On the 12,416-row held-out test split at validation threshold 0.56093: precision 0.9938, recall 0.9846, F1 0.9892, confusion matrix `[[5880, 40], [100, 6396]]`, false-positive rate 0.68%, 100 false negatives, average precision 0.9991, and ROC-AUC 0.9991. These unusually strong internal results must not be read as current phishing-detection performance: the dataset merges older corpora, its positive label combines spam and phishing, local provenance and constituent rights are not verified, and the split cannot group latent sources or campaigns. The model is not connected to production or to a confirmed-threat verdict.

## Local inference

`email_model.py` exposes `predict_email(text, artifact_path)` for offline research use. It masks obvious address/link/IP strings, bounds input size, checks the artifact schema, and returns an uncalibrated score with the source-class wording `spam_or_phishing_proxy`. It makes no network request and is not imported by backend application code.

## Independent external evaluation

The training CSV has only `text_combined,label`. It contains no sender, campaign, thread, source/corpus ID, or structured timestamp. Its existing holdout therefore cannot establish source-level or chronological generalization. For a meaningful independent evaluation, provide newly collected messages with documented labels and source/campaign provenance, plus collection timestamps if chronological performance matters. Explain label adjudication and ensure the messages do not come from the training corpus where possible.

`evaluate_external.py` loads the saved artifact, applies the shared `normalize_email_text` preprocessing, scores with the threshold stored in the artifact, and writes an aggregate-only report. It does not train, tune, filter rows, or overwrite an existing report. It rejects missing/unknown labels and malformed rows. The required input columns are `email_text,label`; optional source-level metrics can be requested with a documented source identifier column. Additional columns are ignored unless selected as that source column.

Every invocation must state the mapping from raw CSV labels to model labels 0/1, the meaning of both mapped labels, and whether the evaluation target is `spam`, `phishing`, or `mixed_spam_phishing`. The current model's positive class was trained as combined spam/phishing. An evaluation labeled phishing therefore measures transfer to the narrower phishing label; it does not change what the model learned. Spam-only labels cannot be reported as phishing results.

Example for a genuinely phishing-labeled external dataset (replace descriptions and filenames with the dataset's real documentation):

```powershell
python ml-training\email-detection\evaluate_external.py `
  path\to\independent-labeled-email.csv `
  --artifact ml-training\email-detection\models\email-tfidf-logreg-v0.1.0-research-73a5c541.joblib `
  --report ml-training\email-detection\reports\external-phishing-evaluation.json `
  --text-column email_text --label-column label `
  --label-map '{"legitimate":0,"confirmed_phishing":1}' `
  --target-type phishing `
  --negative-label-meaning "reviewed non-phishing email" `
  --positive-label-meaning "reviewed phishing email"
```

To break metrics down by a dataset-provided source identifier, add `--source-column source_id`; report keys contain hashes of source values rather than those values. Reports include precision, recall, F1, confusion matrix, FPR, false negatives, average precision, ROC-AUC where both classes are present, dataset/model hashes, and the fixed threshold. No independent evaluation dataset is currently present in the repository.
