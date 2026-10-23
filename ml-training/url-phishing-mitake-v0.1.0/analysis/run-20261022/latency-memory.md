# Offline single-URL inference and memory benchmark

These are local process measurements, not web-service or production latency.

- Prepared data SHA-256: `1ea71ccfc303a5014e896b9c901804ee3fd193305568865c4b921c52bbd3c542`
- Model SHA-256: `cb222a8481750df4e9fba9b22905b642aa69780d0cbb867f6bd4825da9875cfc`
- Cold process startup to worker ready: 1.765048 s
- Model load: 2.740112 s
- First prediction after load: 0.016834 s
- Warm predictions: n=500, warmup=5; min=0.000931 s, median=0.002905 s, p95=0.004583 s, p99=0.005412 s, max=0.007588 s
- Memory method: Windows GetProcessMemoryInfo (process working set)
- Baseline before model load: 113.07 MiB
- After model load: 227.26 MiB
- Peak after inference: 268.27 MiB

Predictions call the existing backend predict_url path with its lru-cached artifact already loaded, so each includes file stat/cache lookup, shared URL normalization, TF-IDF transform, and one-row predict_proba; excludes dataset reading, JSON/report generation, and uncached artifact loading per prediction. This is an offline process benchmark, not web-service latency.

Input values were sampled from the consumed test partition for timing only; they were never written to this report.
