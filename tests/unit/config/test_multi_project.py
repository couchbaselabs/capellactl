"""CAP-040 AC1: multi-project files are validated."""
from __future__ import annotations

import pytest

from capellactl.config.loader import ConfigError, load_config

MULTI = """\
apiVersion: capellactl/v1
organizationId: org-1
projects:
  - name: demo
    clusters:
      - name: main
        cloudProvider: {type: aws, region: us-east-1, cidr: 10.10.0.0/24}
        availability: {type: multi}
        support: {plan: developer pro}
        serviceGroups:
          - node: {compute: {cpu: 4, ram: 16}, disk: {type: gp3, storage: 50, iops: 3000}}
            numOfNodes: 3
            services: [data, index, query]
  - name: non-prod
    clusters:
      - name: main
        cloudProvider: {type: aws, region: us-east-1, cidr: 10.10.0.0/24}
        availability: {type: multi}
        support: {plan: developer pro}
        serviceGroups:
          - node: {compute: {cpu: 4, ram: 16}, disk: {type: gp3, storage: 50, iops: 3000}}
            numOfNodes: 3
            services: [data, index, query]
"""


def _load(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text)
    return load_config(p, env={})


def _err(tmp_path, text):
    with pytest.raises(ConfigError) as ei:
        _load(tmp_path, text)
    return str(ei.value)


@pytest.mark.story("CAP-040", "AC1")
def test_multi_ac1_validate_and_paths(tmp_path):
    cfg = _load(tmp_path, MULTI)
    assert cfg.project_names() == ["demo", "non-prod"] and len(cfg.clusters) == 2
    assert cfg.summary().startswith("Configuration valid: 2 projects, 2 clusters")
    msg = _err(tmp_path, MULTI.replace("numOfNodes: 3\n            services: [data, index, query]\n",
                                       "numOfNodes: 2\n            services: [data, index, query]\n", 2)
               .replace("numOfNodes: 2", "numOfNodes: 3", 1))
    assert "projects[1].clusters[0].serviceGroups[0].numOfNodes: must be between 3 and 27" in msg


@pytest.mark.story("CAP-040", "AC1")
def test_multi_ac1_name_rules(tmp_path):
    # same cluster name and network in different projects: fine (Capella allows it)
    _load(tmp_path, MULTI)
    # duplicate cluster in one project
    dup = MULTI.replace("  - name: non-prod\n    clusters:\n", "")
    assert "duplicate cluster name 'main'" in _err(tmp_path, dup)
    # duplicate project names
    assert "duplicate project name 'demo'" in _err(tmp_path, MULTI.replace("name: non-prod", "name: demo"))
    # both forms at once
    both = MULTI.replace("projects:\n", "project: {name: x}\nprojects:\n")
    assert "use either projects: or the single-project project:/clusters:, not both" in _err(tmp_path, both)
