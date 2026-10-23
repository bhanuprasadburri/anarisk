# Independent URL evaluation audit

This workspace inventories candidate datasets and calculates privacy-preserving overlaps. It does not train a model, select a threshold, modify the Mitake baseline, or access URLs on the network.

## Reproduce

From the repository root, use the existing ML environment (which contains the pinned `tldextract` snapshot dependency):

```powershell
backend\.venv-ml\Scripts\python.exe ml-training\independent-url-evaluation-v0.1.0\audit.py
backend\.venv-ml\Scripts\python.exe -m pytest ml-training\independent-url-evaluation-v0.1.0\tests -q
```

The script reads local files under `ml-training/data/`, checks the PhishVN ZIP without extracting it, validates the embedded file manifest, and writes aggregate results here. Raw candidate datasets remain ignored by `ml-training/.gitignore`; `/sources/*` is also ignored here. URLs, domains, individual hashes, and raw rows are never serialized to reports. Do not add source archives or datasets to Git.

The audit requires publisher documentation for every label mapping and rights claim. A local filename, row count, matching schema, or feature resemblance does not authenticate a copy. All three candidate identity/right decisions remain gated in this workspace, so the evaluator intentionally does not accept candidate labels as definitive or evaluate the model.

The full model evaluation is a later, separately authorized phase. See `EVALUATION_PROTOCOL.md`.
