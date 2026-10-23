# Locked future evaluation protocol (pre-comparison)

Status: written before any model comparison on these candidates. No candidate has been approved as a locked test set. The Mitake test partition is consumed and may appear only as historical context; it must not guide future feature, preprocessing, model, or threshold choices.

## Entry gate

Before accepting a dataset, preserve the publisher page/version, acquisition receipt or official download, archive checksum, included license/attribution, source-specific terms, label documentation, and any access agreement. The exact local bytes must be linked to that acquisition record. Resolve upstream license restrictions and intended use (private research, commercial use, model training and model-weight distribution separately). Ambiguous terms mean stop and `BLOCKED_PENDING_RIGHTS_OR_PROVENANCE_REVIEW`.

Accept only URL strings and documented labels. Verify that the target is phishing rather than a broader abuse/fraud category. Record the publisher label map and explicit conversion to `benign=0`, `phishing=1`; quarantine unrecognized labels. Do not use engineered features as URL substitutes. Preserve source IDs and dates with documented semantics. `scraped_at`/download time is not an observation date.

## Data and partition rules

1. Hash and inventory immutable source bytes before transformation. Retain source rows only under applicable rights and keep them out of Git by default.
2. Apply `backend.app.services.url_model_features.normalize_url` exactly as the model inference workflow does. Reject malformed URLs with reason counts. Never visit, resolve, or transmit dataset URLs.
3. Audit exact raw duplicates, normalized URL duplicates, conflicting labels, source overlap, and domain overlap. Exclude conflicting URL labels by a predeclared deterministic rule and report counts; do not silently drop difficult samples. For benchmark reporting, preserve a documented official split if verified and compatible; report its original grouping limitations.
4. Construct development, calibration, and final partitions by connected groups that join the same normalized URL, registrable domain (AnaRisk `tldextract` bundled PSL snapshot), and reliable source/campaign IDs. A group must occur in one partition only. Persist deterministic membership hashes and code/version/config hashes; never serialize URL values in reports.
5. Use chronological group partitioning only when source-attested observation timestamps are trustworthy. For dated PhishVN groups, order by documented `collected_at`; exclude or isolate undated examples according to a published rule. Because its benign records include many undated observations, this does not by itself support a complete balanced chronological test. Do not substitute `scraped_at` for event time.
6. Partition groups before fitting vectorizers or any preprocessing. Train on development only, select candidate/model parameters on grouped validation only, and calibrate/select threshold on a separate calibration partition. Keep a final independent test locked and unopened until the protocol, candidate, threshold, and analysis are frozen.
7. If a verified, sufficiently sized source-aware grouping is unavailable, say so and do not call the set independent. A publisher-distinct data source alone is not sufficient.

## Required reporting

Report dataset/version hashes, license and attribution record, mapping/exclusions, support and prevalence, counts/denominators, grouped split composition, duplicate/conflict counts, and code/environment/seed. At fixed validation-selected threshold report precision, recall, F1, specificity, FPR, FNR, confusion matrix with explicit `[benign, phishing]` ordering, and false-positive/negative counts. Report PR-AUC (average precision) and ROC-AUC with prevalence/context. Give 95% uncertainty intervals using registrable-domain cluster bootstrap where supported; record seed and resampling unit. Show source/time/subgroup metrics only where sample sizes support them. Include raw proportions alongside intervals.

No threshold, model, preprocessing, or subgroup rule may be changed after observing final-test results. Any adaptation consumes that test; the next final claim requires another locked dataset. Report test once, retain its signed/hashed prediction output privately if rights allow, and keep published reports aggregate-only. The existing fixed threshold `0.778009` can be reported for historical comparison only if preprocessing and target meaning match; it is not assumed calibrated for a new prevalence or target definition.

## Current gate result

No candidate can enter development/calibration or final-test evaluation yet. PhishVN has the best documented source/timestamp/schema among the candidates, but its positive class is broader anti-fraud/abuse and publisher file identity is not established for the local ZIP. PhiLegit has a substantial overlap with the local LegitPhish candidate and source/license authentication is missing. The local LegitPhish file contains engineered features rather than the model's URL input and is unauthenticated. Resolve those gates first; do not train or compare in this audit phase.
