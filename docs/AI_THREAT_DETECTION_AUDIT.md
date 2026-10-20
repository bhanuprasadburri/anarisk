# AnaRisk threat detection: implementation audit

Audit date: 2026-10-20. This document maps the current repository to the evidence it can actually use. It is not a security certification.

## Implementation checklist

| Capability | Code path | Current behavior and limitation |
|---|---|---|
| Risk scoring | `backend/app/services/scoring.py`, `backend/app/services/analysis.py` | Weighted aggregation of four rule-based signal scores. Weights and severity thresholds are configurable but unvalidated. The stored `confidence_score` is a hand-built evidence/availability/corroboration measure, not a calibrated probability. |
| URL signals | `backend/app/services/detection/url_risk.py`, `backend/app/utils/urls.py` | Parses submitted/stored URLs for structure, hostname, and configured indicators. It does not fetch the URL during detection and does not check a live reputation feed. |
| Impersonation | `backend/app/services/detection/impersonation.py` | Compares entity identifiers and text against stored brand references; depends on reference quality. |
| Logo similarity | `backend/app/services/detection/brand_logo.py`, `backend/app/utils/images.py` | Compares supplied/stored image evidence with reference assets. A similarity is not proof of impersonation. |
| Behavioral signals | `backend/app/services/detection/behavior.py` | Uses entities and collection records already in AnaRisk. It cannot infer platform-wide behavior without a real collection source. |
| Analysis tools | `backend/app/services/tools/` and `backend/app/api/v1/tools.py` | Rule-based URL, email/job, social-profile and image tools. Their input and limitations are documented per result; these are not trained production classifiers. |
| AI copilot | `backend/app/services/assistant.py`, `backend/app/services/ai/` | Provider abstraction supports deterministic retrieval (`AI_PROVIDER=none`) and optional OpenAI-compatible interpretation. AI output is not authoritative threat evidence and does not set risk scores. |
| Integrations | `backend/app/services/integrations.py`, `backend/app/services/connectors/` | Provider catalog/configuration exists. The registered sync connector is `sample-listings`, which produces synthetic data; saved third-party credentials do not imply working collection. |
| Scheduled work | `backend/app/services/scheduler.py`, `backend/app/services/monitoring.py` | Persistent scheduler processes configured monitoring targets (currently application/package monitoring), not an internet-wide discovery crawler or threat-feed updater. |
| Evidence, tenancy, audit | `backend/app/models/entity.py`, `backend/app/models/feedback.py`, `backend/app/repositories/access.py`, `backend/app/services/audit.py` | Evidence, assessments, signal history, feedback and brand-scoped access exist. Existing user feedback is not automatically promoted to training labels. |
| Model training/evaluation | `backend/scripts/` | No model training, model registry, or held-out model evaluation pipeline was present at audit time. |

## Data-source decision record

| Source | Intended use | Availability, terms, and decision |
|---|---|---|
| [PhreshPhish](https://huggingface.co/datasets/phreshphish/phreshphish) | Historical phishing webpage/URL research only | Dataset card identifies URL + HTML pairs, binary `phish`/`benign` labels, dates, target and language; CC BY 4.0 and anti-phishing research use. Full dataset is 36.6 GB. Suitable only for offline research with attribution and careful shard selection; do not open the embedded URLs or render HTML. No rows have been downloaded or used in this repository yet. |
| [PhishTank](https://phishtank.org/developer_info.php) | Current verified phishing indicators, separate from training | Official docs describe downloadable verified/online feeds, hourly refresh, and application keys; without a key, downloads are limited to a few per day. No key is configured and no feed integration is claimed. Review Cisco/PhishTank terms before production use. |
| [URLhaus](https://urlhaus.abuse.ch/api/) | Malware-distribution URL intelligence, not phishing labels | Community API requires an Auth-Key and is subject to fair-use principles; commercial/for-profit needs may require its paid enhanced API. Its scope is malware distribution, not phishing. Not added to phishing training or production scoring. |
| [OpenPhish](https://openphish.com/terms.html) | Potential current phishing feed | Community feed is available with terms, but OpenPhish terms restrict business/security operations and product use without prior written consent. Not used or integrated for this project. |
| CIC datasets | Network intrusion tasks | Not selected: AnaRisk does not collect packet/flow telemetry for those datasets, so such a model would not correspond to supported application inputs. |

## Current claims that are supported

- AnaRisk can run explainable heuristic checks against records supplied to or collected by the app.
- It can persist evidence and assessments, distinguish unavailable signals from low risk, and require human review.
- It does **not** currently provide validated ML risk predictions, an enabled external threat feed, or continuous internet-wide monitoring.
- A new offline URL research pipeline is being added separately. Until it has a dataset audit, completed training, leakage-resistant held-out evaluation, and an explicit deployment decision, it will not affect production risk scores.
