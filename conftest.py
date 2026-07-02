"""
conftest.py — makes the full suite runnable as one pytest invocation.

Pre-existing bug (found 2026-07-02): tests/test_apify_quota_handling.py
installs stub modules via sys.modules.setdefault("email_gen", ...) etc.
Those stubs lack names like BROKER_COMP_LINE, so any later-collected test
importing the real module (tests/test_ohio_offer_preview.py) exploded with
ImportError and the WHOLE suite failed collection. Individually the files
passed, which hid the problem.

Fix: import the real modules first, at session start. setdefault() then
becomes a no-op and every test sees the real modules (the quota tests
monkeypatch what they need explicitly, so they still pass).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config          # noqa: F401,E402
import offer           # noqa: F401,E402
import email_gen       # noqa: F401,E402
import dedup           # noqa: F401,E402
import gmail_send      # noqa: F401,E402
import ghl_push        # noqa: F401,E402
