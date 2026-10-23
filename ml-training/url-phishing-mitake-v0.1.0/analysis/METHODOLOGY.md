# URL model descriptive analysis and benchmark

This analysis keeps the v0.1.0 research artifact, source/prepared data, selected threshold, and existing reports unchanged. It scores the existing validation and already-consumed test partitions only to describe errors and operating characteristics. It does not select features, models, or thresholds. All URL parsing is local; no DNS, HTTP, browser, or third-party lookup is used.

## Inputs and safeguards

- Prepared CSV: `../data/prepared.csv`, columns `url,label,domain_group_hash`.
- Artifact: `../models/url-char-tfidf-mitake-v0.1.0-research-1ea71ccf.joblib`.
- Existing evaluation: `../reports/evaluation.json`.
- Label order is benign `0`, phishing `1`; the fixed threshold is read from the saved artifact and checked against the existing evaluation report.
- URL feature extraction calls AnaRisk's shared `normalize_url`; domain features use the bundled Public Suffix List snapshot through the existing `tldextract` setup.
- Prepared URLs are already normalized. Fragments cannot be recovered because normalization strips them; they are reported as unavailable. Other schemes are rejected by the shared normalizer and therefore are not represented.
- Domain-separated splits mean every validation/test registrable domain is unseen in training. The domain-frequency group therefore collapses to `unseen_in_training`; these data cannot estimate how errors vary for domains seen at different training frequencies.
- Reports contain aggregate feature groups and counts only. They do not include URL values, host/domain values, row identifiers, query values, or examples.

## Metrics and uncertainty

The report includes class prevalence, confusion matrices with true rows `[benign, phishing]` and predicted columns `[benign, phishing]`, and denominators for FPR, FNR, precision, recall, specificity, and F1. Average precision and ROC-AUC are score-based. Fixed-threshold rates have 95% Clopper-Pearson intervals. Percentile cluster bootstrap intervals resample whole registrable-domain groups with replacement, using seed `440221` and 1,000 replicates by default. These intervals describe variation in this dataset's domain groups; they do not establish independent sources or current real-world performance. Feature strata are descriptive associations, not causal explanations.

## Latency and memory

The benchmark starts a new Python subprocess and uses the backend's existing cached artifact loader and `predict_url` function. It separately reports parent-observed process startup/import/input initialization through a pre-load marker, uncached model load, first prediction after load, and warm one-URL latencies. Each prediction includes file stat/cache lookup, shared URL normalization, TF-IDF transform, and one-row prediction; it excludes uncached artifact loading per prediction, dataset reading, report generation, and network/service overhead. Its sample consists of evenly spaced URLs from the existing consumed test partition used only as timing inputs; no sample values are saved. Batch throughput from the original report is included only as separate context.

Memory is process-specific: Windows uses `GetProcessMemoryInfo` working-set values; Linux uses `/proc/self/statm` for current RSS and `resource.getrusage` for peak RSS. Unsupported platforms return null values and a reason. The baseline is after Python imports and benchmark-input parsing but before loading the model.

## Reproduction

Run from repository root in PowerShell using the existing ML virtual environment:

```powershell
$env:PYTHONPATH = "$(Get-Location)\backend;$(Get-Location)\ml-training\url-phishing-mitake-v0.1.0"
$Python = ".\backend\.venv-ml\Scripts\python.exe"
$Experiment = ".\ml-training\url-phishing-mitake-v0.1.0"
$Run = "$Experiment\analysis\run-20261022"

& $Python "$Experiment\analyze_errors.py" `
  "$Experiment\data\prepared.csv" `
  "$Experiment\models\url-char-tfidf-mitake-v0.1.0-research-1ea71ccf.joblib" `
  --baseline "$Experiment\reports\evaluation.json" `
  --output "$Run" --seed 440221 --replicates 1000

& $Python "$Experiment\benchmark_inference.py" `
  "$Experiment\data\prepared.csv" `
  "$Experiment\models\url-char-tfidf-mitake-v0.1.0-research-1ea71ccf.joblib" `
  --output "$Run\latency-memory.json" --sample-count 500

Push-Location $Experiment
& $Python -m pytest tests -q
Pop-Location
```

Output paths must be new: the analysis command intentionally refuses to overwrite an existing run directory. The report must be treated as exploratory because the test partition was already consumed and the candidate data's provenance/source independence remain unresolved.
