# AnaRisk URL phishing character TF-IDF research model

## Intended use

Private offline anti-phishing research only. This model is not a production verdict, is not connected to AnaRisk findings or risk scoring, and is not approved for staging or deployment. Do not redistribute the dataset or model artifact.

## Dataset and labels

- Source listing: https://huggingface.co/datasets/Mitake/PhishingURLsANDBenignURLs
- Local raw dataset SHA-256: `a1e3fc9df5b9068b2f28237af3fe605801165daf7d1c4cb41f10c372fb57321c`
- Prepared dataset SHA-256: `1ea71ccfc303a5014e896b9c901804ee3fd193305568865c4b921c52bbd3c542`
- Label mapping: `0 = benign`, `1 = phishing` (user-confirmed; publisher README/card does not explain it).
- Declared dataset license: CC BY-SA 4.0. Source lineage and upstream rights have not been independently verified; no conclusion is made about model-weight share-alike treatment.
- Attribution: Mitake, PhishingURLsANDBenignURLs, CC BY-SA 4.0, https://huggingface.co/datasets/Mitake/PhishingURLsANDBenignURLs. Changes: URL normalization, conflict/duplicate handling, and domain-separated splits.

## Evaluation

- Model version: `anarisk-url-phish-mitake-v0.1.0-research-1ea71ccf`
- Selected estimator: `logistic_regression`
- Validation-selected threshold: `0.7780090477833166` (validation FPR target <= 1%; no test tuning).
- Test rows: 150045; phishing prevalence: 0.2638.
- Precision: 0.8334; recall: 0.8087; F1: 0.8209; specificity: 0.9421; balanced accuracy: 0.8754.
- Average precision: 0.9404; ROC-AUC: 0.9710.
- FPR: 0.0579; FNR: 0.1913; FP: 6401; FN: 7572.
- Confusion matrix, true rows `[benign, phishing]`, predicted columns `[benign, phishing]`: `[[104058, 6401], [7572, 32014]]`.
- Domain/normalized URL disjointness: `True`.

## Limitations

- The candidate data shares 442788 normalized URL hashes and 123407 registrable-domain hashes with the legacy source dataset; this is not an independent source-level benchmark, and a clean same-test baseline comparison is invalid.
- No reliable timestamps, source IDs, or label verification history are available.
- Dataset source revision and local byte identity are not verified.
- Metrics reflect this dataset's labels and class prevalence, not current real-world traffic.
- No claims of production generalization or deployment readiness are made.
