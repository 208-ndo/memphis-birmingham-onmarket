"""
sitecustomize.py — Apify quota fail-fast guard.

Python imports this file automatically when the repo root is on sys.path
(normal `python main.py` behavior). The goal is simple: if Apify returns a
quota/billing hard-limit error, stop the process immediately before scraper.py's
broad `except Exception` can catch it and continue through every remaining band.

This prevents quota-blocked runs from:
- attempting all remaining Zillow/Google actor calls
- writing 0-lead dashboard files
- saving 0 leads to overflow
- committing misleading empty data after a failed scrape
"""

import logging
import os

log = logging.getLogger(__name__)

APIFY_QUOTA_ENV = "APIFY_QUOTA_BLOCKED"


class ApifyQuotaBlocked(BaseException):
    """Raised on Apify account quota/billing hard-limit errors.

    This intentionally inherits from BaseException, not Exception, so existing
    broad `except Exception` retry/continue blocks do not swallow it.
    """


def _is_apify_quota_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    quota_markers = [
        "monthly usage hard limit exceeded",
        "usage hard limit exceeded",
        "quota exceeded",
    ]
    return any(marker in text for marker in quota_markers)


try:
    import apify_client as _apify_client

    _OriginalApifyClient = _apify_client.ApifyClient

    class _GuardedActorClient:
        def __init__(self, actor_client):
            self._actor_client = actor_client

        def call(self, *args, **kwargs):
            try:
                return self._actor_client.call(*args, **kwargs)
            except BaseException as exc:
                if _is_apify_quota_error(exc):
                    os.environ[APIFY_QUOTA_ENV] = "true"
                    msg = (
                        "APIFY QUOTA BLOCKED — preserving previous dashboard data "
                        "and stopping paid actor attempts. "
                        f"Original error: {exc}"
                    )
                    log.error(msg)
                    raise ApifyQuotaBlocked(msg) from exc
                raise

        def __getattr__(self, name):
            return getattr(self._actor_client, name)

    class GuardedApifyClient(_OriginalApifyClient):
        def actor(self, *args, **kwargs):
            return _GuardedActorClient(super().actor(*args, **kwargs))

    _apify_client.ApifyClient = GuardedApifyClient

except Exception as exc:  # pragma: no cover - guard must never break imports
    log.debug(f"Apify quota guard not installed: {exc}")
