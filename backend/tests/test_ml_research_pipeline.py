from __future__ import annotations

from scripts.ml.train_url_model import features, group_key, grouped_split
from scripts.ml.url_dataset import normalize_url


def test_url_normalization_does_not_fetch_and_removes_fragments_or_credentials():
    assert normalize_url("HTTPS://User:pass@ExAmPle.com/a?q=1#fragment") == "https://example.com/a?q=1"
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("not a url\nhttps://example.com") == ""


def test_url_features_are_fixed_width_and_finite():
    values = features("https://login-example.test/verify?account=2")
    assert len(values) == 15
    assert all(0 <= x <= 1 for x in values)
    assert group_key("https://Sub.Example.test/login") == "sub.example.test"


def test_grouped_split_has_no_hostname_leakage_and_is_deterministic():
    rows = []
    for n in range(80):
        label = n % 2
        rows.append({"url": f"https://host-{n}.example.test/{label}", "label": label})
        rows.append({"url": f"https://host-{n}.example.test/second-{label}", "label": label})
    a = grouped_split(rows, seed=17)
    b = grouped_split(rows, seed=17)
    assert a == b
    hosts = {k: {group_key(row["url"]) for row in val} for k, val in a.items()}
    assert hosts["train"].isdisjoint(hosts["validation"])
    assert len(a["train"]) + len(a["validation"]) == len(rows)
