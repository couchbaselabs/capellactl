"""capellactl: declarative, idempotent management of Couchbase Capella environments."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("capellactl")  # set at build time from the git tag (scripts/version.py, CAP-043)
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"
API_VERSION = "v4.0"
DEFAULT_BASE_URL = "https://cloudapi.cloud.couchbase.com"
LICENSE = "Apache-2.0"  # SPDX id; full terms in LICENSE, copyright in NOTICE (CAP-044)
COPYRIGHT = "Copyright 2026 Couchbase, Inc."
