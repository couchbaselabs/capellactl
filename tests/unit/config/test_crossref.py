"""CAP-002 AC4: cross-reference checks."""
from __future__ import annotations

import pytest

from capellactl.config.loader import ConfigError, load_config
from tests.conftest import MINIMAL

ENV = {"CAPELLA_ORG_ID": "o", "PW": "Abcdef1!x"}
DATA = """
    buckets:
      - name: orders
        memoryAllocationInMb: 1024
        scopes:
          - name: inventory
            collections: [ {{ name: items }} ]
    databaseCredentials:
      - name: app
        access:
          - privileges: [read]
            resources:
              buckets:
                - name: {bucket}
                  {extra}
"""


def _load(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    return load_config(p, env=ENV)


def _err(tmp_path, text) -> str:
    with pytest.raises(ConfigError) as ei:
        _load(tmp_path, text)
    return str(ei.value)


@pytest.mark.story("CAP-002", "AC4")
def test_crossref_ac4_unknown_bucket(tmp_path):
    msg = _err(tmp_path, MINIMAL + DATA.format(bucket="ordrs", extra=""))
    assert "credential app › access[0].resources.buckets[0].name" in msg
    assert "bucket 'ordrs', which capella.yaml does not list for cluster 'nova-dev-01'" in msg


@pytest.mark.story("CAP-002", "AC4")
def test_crossref_ac4_unknown_scope_and_collection(tmp_path):
    msg = _err(tmp_path, MINIMAL + DATA.format(bucket="orders", extra="scopes: [ { name: billing } ]"))
    assert "scope 'billing' is not defined in bucket 'orders'" in msg
    msg = _err(tmp_path, MINIMAL + DATA.format(bucket="orders",
                                               extra="scopes: [ { name: inventory, collections: [nope] } ]"))
    assert "collection 'nope' is not defined in orders.inventory" in msg


@pytest.mark.story("CAP-002", "AC4")
def test_crossref_ac4_external_bucket_allowed(tmp_path):
    cfg = _load(tmp_path, MINIMAL + DATA.format(bucket="legacy", extra="external: true"))
    assert cfg.clusters[0]["databaseCredentials"][0]["access"][0]["resources"]["buckets"][0]["external"] is True


@pytest.mark.story("CAP-002", "AC4")
@pytest.mark.parametrize("kind,snippet,label", [
    ("bucket", "    buckets:\n      - name: a\n      - name: a\n", "duplicate bucket name 'a'"),
    ("cidr", "    allowedCidrs:\n      - cidr: 203.0.113.10\n      - cidr: 203.0.113.10/32\n", "duplicate allowed CIDR name"),
    ("credential", "    databaseCredentials:\n      - name: u1\n        access: [ { privileges: [read] } ]\n"
                   "      - name: u1\n        access: [ { privileges: [read] } ]\n", "duplicate credential name 'u1'"),
])
def test_crossref_ac4_duplicate_names(tmp_path, kind, snippet, label):
    assert label in _err(tmp_path, MINIMAL + snippet)


@pytest.mark.story("CAP-002", "AC4")
def test_crossref_ac4_duplicate_cluster_names(tmp_path):
    second = MINIMAL.split("clusters:\n", 1)[1]
    assert "duplicate cluster name 'nova-dev-01'" in _err(tmp_path, MINIMAL + second)


@pytest.mark.story("CAP-002", "AC4")
def test_crossref_ac4_disk_type_matches_provider(tmp_path):
    msg = _err(tmp_path, MINIMAL.replace("type: aws", "type: gcp"))
    assert "disk type gp3 is not valid for gcp (use: pd-ssd)" in msg


@pytest.mark.story("CAP-002", "AC4")
def test_crossref_ac4_data_service_required(tmp_path):
    msg = _err(tmp_path, MINIMAL.replace("services: [data, index, query]", "services: [index, query]"))
    assert "at least one service group must run the data service" in msg


@pytest.mark.story("CAP-002", "AC4")
def test_crossref_ac4_cluster_cidr_valid_and_not_overlapping(tmp_path):
    msg = _err(tmp_path, MINIMAL.replace("cidr: 10.10.0.0/24", "cidr: 10.10.0.5/24"))
    assert "10.10.0.5/24 is not a network address (did you mean 10.10.0.0/24?)" in msg
    second = MINIMAL.split("clusters:\n", 1)[1].replace("name: nova-dev-01", "name: nova-dev-02") \
        .replace("cidr: 10.10.0.0/24", "cidr: 10.10.0.128/25")
    msg = _err(tmp_path, MINIMAL + second)
    assert "10.10.0.128/25 overlaps the network of cluster 'nova-dev-01' (10.10.0.0/24)" in msg
