"""CAP-003 AC6: structured errors."""
from __future__ import annotations

import json

import pytest

from capellactl.api import errors as e


@pytest.mark.story("CAP-003", "AC6")
@pytest.mark.parametrize("status,cls", [(401, e.Unauthorized), (403, e.Forbidden), (404, e.NotFound),
                                        (409, e.Conflict), (412, e.PreconditionFailed), (422, e.ValidationFailed),
                                        (429, e.RateLimited), (500, e.ServerError), (503, e.ServerError)])
def test_errors_ac6_parse_error_body(status, cls):
    body = json.dumps({"httpStatusCode": status, "code": 4001, "message": "bad thing", "hint": "do this"})
    err = e.error_from_response(status, body, "POST", "/v4/x")
    assert isinstance(err, cls)
    assert (err.http_status, err.code, err.message, err.hint) == (status, 4001, "bad thing", "do this")


@pytest.mark.story("CAP-003", "AC6")
def test_errors_ac6_non_json_body():
    err = e.error_from_response(502, "<html>" + "x" * 500, "GET", "/v4/x")
    assert isinstance(err, e.ServerError)
    assert err.message.startswith("HTTP 502: <html>") and len(err.message) < 230
