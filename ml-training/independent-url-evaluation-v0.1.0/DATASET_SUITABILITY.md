# Dataset suitability decisions

These decisions are for this project's URL-string model and this audit state, not general judgments about the datasets.

| Dataset | Decision | Rationale / next gate |
|---|---|---|
| PhishVN v3.1.0 open | `BLOCKED_PENDING_RIGHTS_OR_PROVENANCE_REVIEW` | Strongest documentation, source/tier fields and a source-attested `collected_at` for some records. Local archive has not been authenticated to official acquisition; positive target includes broader anti-fraud, and substantial positives are bronze/community sourced. CC BY 4.0 attribution is explicit, but upstream-source terms and intended commercial/model-weight distribution remain unresolved. The local normalized overlap with Mitake is measurable and nonzero (exact counts in overlap report). Could be a development/calibration candidate only after intended label scope and rights review; not a locked credential-phishing test as-is. |
| PhiLegit-100K | `BLOCKED_PENDING_RIGHTS_OR_PROVENANCE_REVIEW` | Current official card claims CC BY 4.0 and describes `PhiLegit-100K.csv`, plus an included README, but no publisher payload was acquired and the local CSV cannot be byte-linked to it. Label meaning is provisional from the local header. No temporal identifiers. Local `source_dataset` reports 19,617 rows from LegitPhish and 13,571 "Both", so it is not independent of LegitPhish; normalized URL overlap between the local files is high. Resolve upstream rights and mapping. |
| LegitPhish v2 | `BLOCKED_PENDING_RIGHTS_OR_PROVENANCE_REVIEW` | Publisher card/paper declare CC BY 4.0 and document labels. The local feature-style CSV does include a `URL` column, but its identity is unauthenticated; only that string field (not engineered feature columns) could feed the character model after source verification. No trustworthy row-level timestamps/source IDs were found in reviewed docs; source licensing/label verification and 101,218-vs-101,219 row discrepancy need clarification. |

No candidate is `ACCEPT_FOR_DEVELOPMENT`, `ACCEPT_FOR_CALIBRATION`, or `CANDIDATE_FOR_LOCKED_FINAL_TEST` at this time. This is an evidence gate, not a finding that every candidate is inherently unusable. No model evaluation was run and no dataset was merged.

## Attribution and rights review checklist

- Archive acquired from official dataset page/download using the applicable access terms; record receipt/date and SHA-256.
- Version/DOI, title, authors/publisher, exact license file/text, attribution statement and modification notice captured with the artifact.
- For PhishVN, evaluate the terms of NCSC/Tin Nhiem Mang, ChongLuaDao and OpenPhish records and applicable restrictions on rehosting/reuse.
- For PhiLegit, resolve rights of PhiUSIIL and LegitPhish contributors and any rights attached to derived/merged records.
- For LegitPhish, resolve upstream URLHaus, PhishTank, UCI and Google/Wikipedia/StackOverflow terms; the dataset's CC BY claim alone may not grant those upstream rights.
- Obtain review for intended private research, commercial use, internal staging, external service, and derived model weights as separate questions. Preserve attribution and assess CC BY 4.0 obligations. Do not infer weight distribution permission.
- Clarify label scope/quality and any access restrictions; document reviewer and decision. Until then, do not train, distribute or deploy derived artifacts.
