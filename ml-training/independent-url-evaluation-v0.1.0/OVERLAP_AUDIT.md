# Privacy-preserving overlap audit

Generated from local files on 2026-10-22 by `audit.py`. Pairwise counts distinguish exact raw URL-string overlap, normalized URL overlap and registrable-domain overlap. JSON entries include left/right denominators for normalized-URL overlap. URL values are hashed in memory for comparisons; only counts/fractions and dataset-wide source counts are saved. No raw URL/host or row hash is serialized. Normalization is AnaRisk's existing inference normalizer; domain grouping uses Mitake's bundled PSL snapshot with online fetching disabled.

The local files for PhiLegit and LegitPhish are not source-authenticated. Treat their counts as comparisons of these local byte sequences, not proof about official releases. PhiLegit's label interpretation is provisional. For label conflicts, only rows with currently mapped labels contribute; counts should not be interpreted as source independence or as validated label disagreement.

## Summary

See `overlap_results.json` for full pairs. The values below compare unique local sets; left/right denominators refer to normalized URLs.

| Pair | Exact raw URL strings shared | Normalized URLs shared | Left/right normalized denominators | Registrable domains shared |
|---|---:|---:|---:|---:|---:|
| PhishVN local ZIP / Mitake training CSV | 1,563 | 1,620 | 53,112 / 863,161 | 1,903 |
| PhishVN local ZIP / legacy malicious_phish | 2 | 69 | 53,112 / 640,652 | 565 |
| PhishVN local ZIP / local PhiLegit | 3 | 12 | 53,112 / 99,858 | 352 |
| PhishVN local ZIP / local LegitPhish candidate | 2 | 7 | 53,112 / 100,196 | 241 |
| Local PhiLegit / Mitake training CSV | 387 | 3,546 | 99,858 / 863,161 | 16,937 |
| Local PhiLegit / legacy malicious_phish | 405 | 407 | 99,858 / 640,652 | 3,680 |
| Local PhiLegit / local LegitPhish candidate | 33,189 | 33,120 | 99,858 / 100,196 | 24,941 |
| Local LegitPhish candidate / Mitake training CSV | 1,299 | 1,322 | 100,196 / 863,161 | 11,395 |
| Local LegitPhish candidate / legacy malicious_phish | 1,299 | 1,298 | 100,196 / 640,652 | 3,077 |

The local PhishVN URL table has 36,909 train, 7,266 validation, and 8,941 test rows. Its supplied partitions have no AnaRisk-normalized URL/domain crossover in this audit. That source split is not an independent AnaRisk benchmark. Local PhiLegit and LegitPhish show substantial overlap. The PhiLegit `source_dataset` column also attributes 19,617 records to LegitPhish plus a 13,571-row combined-source stratum; these are not independent candidate benchmarks.

The local feature-oriented LegitPhish candidate also overlaps Mitake and legacy `malicious_phish.csv` as shown in the JSON; its identity is unverified.
- Legacy `malicious_phish.csv` has phishing, benign, defacement and malware labels. Only phishing and benign are mapped in this audit; other threat classes are counted as ambiguous for this binary target. Do not interpret a conflicting label count from partially mapped legacy rows as a benchmark verdict.

## Limitations

Raw row/source-ID overlap across publishers is unavailable because candidate provenance and compatible identifiers are not established; where common URL string fields exist, exact string overlap is separately reported. Registrable-domain overlap can reflect popular benign properties and does not establish URL reuse. Conversely, URL overlap may be missed if upstream transforms differed. Hashes are not anonymization; no individual hashes are published. Timestamp ranges mean only the field parsed; they do not prove that a date is event time unless its source documentation supports that meaning.
