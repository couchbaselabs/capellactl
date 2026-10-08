"""CAP-013: the deletion-protection reconciler's desired state and diff."""
from __future__ import annotations

import pytest

from capellactl.resources.base import Action, ActionType, Observed
from capellactl.resources.deletion_protection import DeletionProtectionReconciler


def _cluster(protected: bool | None) -> Action:
    observed = None if protected is None else Observed("c-1", {"deletionProtection": protected})
    return Action("cluster", "nova-dev-01", ActionType.NOOP, DeletionProtectionReconciler(), observed=observed)


@pytest.mark.story("CAP-013", "AC3")
@pytest.mark.parametrize("current", [True, False])
def test_protection_ac3_omitted_unchanged(current):
    rec = DeletionProtectionReconciler()
    assert rec.desired_items({"name": "nova-dev-01"}) == []  # nothing to plan, whatever Capella has
    assert rec.desired_items({"name": "nova-dev-01", "deletionProtection": current}) == [current]


@pytest.mark.story("CAP-013", "AC1")
@pytest.mark.parametrize(("desired", "current", "expected"), [
    (True, False, ActionType.UPDATE), (False, True, ActionType.UPDATE),
    (True, True, ActionType.NOOP), (False, False, ActionType.NOOP),
])
def test_protection_ac1_diff(desired, current, expected):
    rec = DeletionProtectionReconciler()
    parent = _cluster(current)
    obs = rec.observe(None, parent)  # type: ignore[arg-type]  # read from the cluster: no API call
    a = rec.diff(None, desired, obs[0], parent)  # type: ignore[arg-type]
    assert a.type is expected
    if expected is ActionType.UPDATE:
        assert [(c.path, c.before, c.after) for c in a.changes] == [("deletionProtection", current, desired)]


@pytest.mark.story("CAP-013", "AC2")
def test_protection_ac2_new_cluster():
    rec = DeletionProtectionReconciler()
    parent = _cluster(None)
    assert rec.diff(None, True, None, parent).type is ActionType.CREATE  # type: ignore[arg-type]
    off = rec.diff(None, False, None, parent)  # type: ignore[arg-type]
    assert off.type is ActionType.NOOP and off.hidden  # new clusters start unprotected: nothing to show
