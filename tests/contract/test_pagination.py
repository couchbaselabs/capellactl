"""CAP-003 AC5: cursor pagination."""
from __future__ import annotations

import pytest
import responses
from responses import matchers

from tests.contract.conftest import BASE

PATH = "/v4/organizations/org-1/projects/p/clusters"


def _page(n: int, items: list[dict], last: int) -> dict:
    pages = {"page": n, "last": last, "perPage": 100, "totalItems": 230}
    if n < last:
        pages["next"] = n + 1
    return {"data": items, "cursor": {"pages": pages, "hrefs": {}}}


@pytest.mark.story("CAP-003", "AC5")
def test_client_ac5_follows_cursor_next(rsps, client):
    items = [{"id": f"c-{i}"} for i in range(230)]
    for n in (1, 2, 3):
        rsps.add(responses.GET, BASE + PATH, json=_page(n, items[(n - 1) * 100: n * 100], 3),
                 match=[matchers.query_param_matcher({"page": str(n), "perPage": "100"})])
    assert len(client.paginate(PATH)) == 230
    assert len(rsps.calls) == 3


@pytest.mark.story("CAP-003", "AC5")
def test_client_ac5_no_cursor_single_page(rsps, client):
    rsps.add(responses.GET, BASE + PATH + "/x/buckets/b/scopes", json={"scopes": [{"name": "_default"}]})
    assert client.paginate(PATH + "/x/buckets/b/scopes", key="scopes") == [{"name": "_default"}]
    assert len(rsps.calls) == 1
