# Exploratory URL phishing error analysis

This report describes existing validation and consumed test partitions. It is not an independent final evaluation and was not used to select or tune anything.

- Model: `anarisk-url-phish-mitake-v0.1.0-research-1ea71ccf`
- Fixed validation-selected threshold: `0.778009048`
- Dataset SHA-256: `1ea71ccfc303a5014e896b9c901804ee3fd193305568865c4b921c52bbd3c542`
- Artifact SHA-256: `cb222a8481750df4e9fba9b22905b642aa69780d0cbb867f6bd4825da9875cfc`

## Partition metrics

| Split | N | Phishing prevalence | FPR (FP / benign) | FNR (FN / phishing) | Precision | Recall | Specificity | F1 | AP | ROC-AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| validation | 108730 | 0.3399 | 0.0100 (717/71774) | 0.1737 (6419/36956) | 0.9771 | 0.8263 | 0.9900 | 0.8954 | 0.9751 | 0.9838 |
| test | 150045 | 0.2638 | 0.0579 (6401/110459) | 0.1913 (7572/39586) | 0.8334 | 0.8087 | 0.9421 | 0.8209 | 0.9404 | 0.9710 |

## 95% uncertainty intervals

Exact binomial intervals treat rows as Bernoulli observations; domain-cluster intervals resample whole domains. Cluster intervals are more relevant under the split design, but neither addresses source independence.

| Split | Metric | Exact binomial interval | Domain-cluster bootstrap interval |
|---|---|---:|---:|
| test | false_positive_rate | [0.0566, 0.0593] | [0.0064, 0.1594] |
| test | false_negative_rate | [0.1874, 0.1952] | [0.1620, 0.2252] |
| test | precision_phishing | [0.8296, 0.8371] | [0.6256, 0.9797] |
| test | recall_phishing | [0.8048, 0.8126] | [0.7748, 0.8380] |
| validation | false_positive_rate | [0.0093, 0.0107] | [0.0076, 0.0127] |
| validation | false_negative_rate | [0.1698, 0.1776] | [0.1523, 0.1948] |
| validation | precision_phishing | [0.9753, 0.9787] | [0.9699, 0.9832] |
| validation | recall_phishing | [0.8224, 0.8302] | [0.8052, 0.8477] |

## Feature group errors

Rates are calculated within the corresponding true class; support and denominators are included. These are descriptive associations, not causes.

### validation

| Feature | Group | Support | Benign support | FP / benign | FPR | Phishing support | FN / phishing | FNR |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| digit_count | 0-0 | 63637 | 46556 | 395/46556 | 0.0085 | 17081 | 3724/17081 | 0.2180 |
| digit_count | 1-3 | 14708 | 6139 | 101/6139 | 0.0165 | 8569 | 1588/8569 | 0.1853 |
| digit_count | 4-7 | 13282 | 10045 | 76/10045 | 0.0076 | 3237 | 572/3237 | 0.1767 |
| digit_count | 8+ | 17103 | 9034 | 145/9034 | 0.0161 | 8069 | 535/8069 | 0.0663 |
| dot_count | 0-1 | 44155 | 37553 | 135/37553 | 0.0036 | 6602 | 2278/6602 | 0.3450 |
| dot_count | 2-3 | 55455 | 32297 | 485/32297 | 0.0150 | 23158 | 3907/23158 | 0.1687 |
| dot_count | 4-7 | 8140 | 1854 | 85/1854 | 0.0458 | 6286 | 227/6286 | 0.0361 |
| dot_count | 8+ | 980 | 70 | 12/70 | 0.1714 | 910 | 7/910 | 0.0077 |
| fragment | unavailable_after_normalization | 108730 | 71774 | 717/71774 | 0.0100 | 36956 | 6419/36956 | 0.1737 |
| hyphen_count | 0-0 | 72376 | 50681 | 497/50681 | 0.0098 | 21695 | 4607/21695 | 0.2124 |
| hyphen_count | 1-3 | 25422 | 12773 | 193/12773 | 0.0151 | 12649 | 1662/12649 | 0.1314 |
| hyphen_count | 4-7 | 6413 | 4763 | 22/4763 | 0.0046 | 1650 | 122/1650 | 0.0739 |
| hyphen_count | 8+ | 4519 | 3557 | 5/3557 | 0.0014 | 962 | 28/962 | 0.0291 |
| ip_literal_host | no | 107857 | 71771 | 715/71771 | 0.0100 | 36086 | 6412/36086 | 0.1777 |
| ip_literal_host | yes | 873 | 3 | 2/3 | 0.6667 | 870 | 7/870 | 0.0080 |
| non_default_port | no | 108474 | 71761 | 717/71761 | 0.0100 | 36713 | 6384/36713 | 0.1739 |
| non_default_port | yes | 256 | 13 | 0/13 | 0.0000 | 243 | 35/243 | 0.1440 |
| path_segments | 0-0 | 44694 | 30361 | 221/30361 | 0.0073 | 14333 | 2673/14333 | 0.1865 |
| path_segments | 1-2 | 37174 | 24403 | 297/24403 | 0.0122 | 12771 | 3049/12771 | 0.2387 |
| path_segments | 3-5 | 22756 | 14237 | 131/14237 | 0.0092 | 8519 | 656/8519 | 0.0770 |
| path_segments | 6+ | 4106 | 2773 | 68/2773 | 0.0245 | 1333 | 41/1333 | 0.0308 |
| prediction_score | [.25,.5) | 8304 | 6620 | 0/6620 | 0.0000 | 1684 | 1684/1684 | 1.0000 |
| prediction_score | [.5,.75) | 5938 | 2913 | 0/2913 | 0.0000 | 3025 | 3025/3025 | 1.0000 |
| prediction_score | [.75,1] | 32009 | 856 | 717/856 | 0.8376 | 31153 | 616/31153 | 0.0198 |
| prediction_score | [0,.25) | 62479 | 61385 | 0/61385 | 0.0000 | 1094 | 1094/1094 | 1.0000 |
| query_string | no | 96332 | 65897 | 512/65897 | 0.0078 | 30435 | 6163/30435 | 0.2025 |
| query_string | yes | 12398 | 5877 | 205/5877 | 0.0349 | 6521 | 256/6521 | 0.0393 |
| scheme | https | 108730 | 71774 | 717/71774 | 0.0100 | 36956 | 6419/36956 | 0.1737 |
| training_domain_frequency | unseen_in_training | 108730 | 71774 | 717/71774 | 0.0100 | 36956 | 6419/36956 | 0.1737 |
| url_length | 0-50 | 70517 | 47520 | 450/47520 | 0.0095 | 22997 | 5389/22997 | 0.2343 |
| url_length | 101-200 | 6451 | 3618 | 115/3618 | 0.0318 | 2833 | 121/2833 | 0.0427 |
| url_length | 201+ | 2634 | 133 | 26/133 | 0.1955 | 2501 | 5/2501 | 0.0020 |
| url_length | 51-100 | 29128 | 20503 | 126/20503 | 0.0061 | 8625 | 904/8625 | 0.1048 |
### test

| Feature | Group | Support | Benign support | FP / benign | FPR | Phishing support | FN / phishing | FNR |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| digit_count | 0-0 | 76397 | 57767 | 402/57767 | 0.0070 | 18630 | 3810/18630 | 0.2045 |
| digit_count | 1-3 | 24880 | 14265 | 147/14265 | 0.0103 | 10615 | 2489/10615 | 0.2345 |
| digit_count | 4-7 | 26307 | 22932 | 3928/22932 | 0.1713 | 3375 | 609/3375 | 0.1804 |
| digit_count | 8+ | 22461 | 15495 | 1924/15495 | 0.1242 | 6966 | 664/6966 | 0.0953 |
| dot_count | 0-1 | 61554 | 52907 | 171/52907 | 0.0032 | 8647 | 3317/8647 | 0.3836 |
| dot_count | 2-3 | 75908 | 54602 | 6175/54602 | 0.1131 | 21306 | 3868/21306 | 0.1815 |
| dot_count | 4-7 | 11617 | 2904 | 51/2904 | 0.0176 | 8713 | 380/8713 | 0.0436 |
| dot_count | 8+ | 966 | 46 | 4/46 | 0.0870 | 920 | 7/920 | 0.0076 |
| fragment | unavailable_after_normalization | 150045 | 110459 | 6401/110459 | 0.0579 | 39586 | 7572/39586 | 0.1913 |
| hyphen_count | 0-0 | 103008 | 77401 | 6111/77401 | 0.0790 | 25607 | 5875/25607 | 0.2294 |
| hyphen_count | 1-3 | 31165 | 18323 | 154/18323 | 0.0084 | 12842 | 1515/12842 | 0.1180 |
| hyphen_count | 4-7 | 9452 | 8539 | 78/8539 | 0.0091 | 913 | 138/913 | 0.1512 |
| hyphen_count | 8+ | 6420 | 6196 | 58/6196 | 0.0094 | 224 | 44/224 | 0.1964 |
| ip_literal_host | no | 149164 | 110457 | 6401/110457 | 0.0580 | 38707 | 7570/38707 | 0.1956 |
| ip_literal_host | yes | 881 | 2 | 0/2 | 0.0000 | 879 | 2/879 | 0.0023 |
| non_default_port | no | 149811 | 110453 | 6401/110453 | 0.0580 | 39358 | 7552/39358 | 0.1919 |
| non_default_port | yes | 234 | 6 | 0/6 | 0.0000 | 228 | 20/228 | 0.0877 |
| path_segments | 0-0 | 55852 | 40721 | 5744/40721 | 0.1411 | 15131 | 2571/15131 | 0.1699 |
| path_segments | 1-2 | 59353 | 43389 | 415/43389 | 0.0096 | 15964 | 4345/15964 | 0.2722 |
| path_segments | 3-5 | 30714 | 23798 | 182/23798 | 0.0076 | 6916 | 611/6916 | 0.0883 |
| path_segments | 6+ | 4126 | 2551 | 60/2551 | 0.0235 | 1575 | 45/1575 | 0.0286 |
| prediction_score | [.25,.5) | 13389 | 11422 | 0/11422 | 0.0000 | 1967 | 1967/1967 | 1.0000 |
| prediction_score | [.5,.75) | 7671 | 3917 | 0/3917 | 0.0000 | 3754 | 3754/3754 | 1.0000 |
| prediction_score | [.75,1] | 39706 | 7008 | 6401/7008 | 0.9134 | 32698 | 684/32698 | 0.0209 |
| prediction_score | [0,.25) | 89279 | 88112 | 0/88112 | 0.0000 | 1167 | 1167/1167 | 1.0000 |
| query_string | no | 127681 | 93922 | 6227/93922 | 0.0663 | 33759 | 7154/33759 | 0.2119 |
| query_string | yes | 22364 | 16537 | 174/16537 | 0.0105 | 5827 | 418/5827 | 0.0717 |
| scheme | https | 150045 | 110459 | 6401/110459 | 0.0579 | 39586 | 7572/39586 | 0.1913 |
| training_domain_frequency | unseen_in_training | 150045 | 110459 | 6401/110459 | 0.0579 | 39586 | 7572/39586 | 0.1913 |
| url_length | 0-50 | 99686 | 74672 | 5963/74672 | 0.0799 | 25014 | 6175/25014 | 0.2469 |
| url_length | 101-200 | 8650 | 5524 | 89/5524 | 0.0161 | 3126 | 148/3126 | 0.0473 |
| url_length | 201+ | 1709 | 575 | 9/575 | 0.0157 | 1134 | 21/1134 | 0.0185 |
| url_length | 51-100 | 40000 | 29688 | 340/29688 | 0.0115 | 10312 | 1228/10312 | 0.1191 |

Registrable domains are disjoint across partitions, so all validation/test domains are unseen in training. This split cannot estimate error rates by within-training-domain frequency.

## Interval methods and limitations

The JSON report gives 95% Clopper–Pearson intervals for fixed-threshold binomial rates and percentile intervals from a seeded bootstrap that resamples whole registrable-domain groups. Cluster intervals estimate variation under this dataset's domain groups; they do not establish source independence. Dataset provenance, labels, source IDs, and timestamps remain unresolved/unavailable.

## Reproduction

From repository root, with the ML environment installed:

```powershell
$env:PYTHONPATH = "$(Get-Location)\backend;$(Get-Location)\ml-training\url-phishing-mitake-v0.1.0"
python ml-training\url-phishing-mitake-v0.1.0\analyze_errors.py `
  ml-training\url-phishing-mitake-v0.1.0\data\prepared.csv `
  ml-training\url-phishing-mitake-v0.1.0\models\url-char-tfidf-mitake-v0.1.0-research-1ea71ccf.joblib `
  --baseline ml-training\url-phishing-mitake-v0.1.0\reports\evaluation.json `
  --output ml-training\url-phishing-mitake-v0.1.0\analysis\run-YYYYMMDD `
  --replicates 1000
```
