"""UI assets are served with Cache-Control: no-cache, so an update reaches the browser immediately.

They had no Cache-Control at all; browsers cached them heuristically and ran old css/js after an update
(live: a fixed stylesheet kept rendering the old layout) while index.html itself was already no-store.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_ui_css_is_revalidated_and_conditional_requests_work():
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as c:
        r = c.get("/layla-ui/css/layla.css")
        assert r.status_code == 200, "PROBE BROKEN: the UI stylesheet is not served"
        assert r.headers.get("cache-control") == "no-cache", dict(r.headers)
        etag = r.headers.get("etag")
        assert etag
        r2 = c.get("/layla-ui/css/layla.css", headers={"If-None-Match": etag})
        assert r2.status_code == 304
