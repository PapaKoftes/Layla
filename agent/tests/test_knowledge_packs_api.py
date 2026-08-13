"""v1.7.5: /knowledge/packs API — list reflects registry + enabled state; POST scopes config."""
import asyncio


def test_list_packs_shape_and_core_always_on():
    from routers.knowledge import knowledge_packs_list

    res = knowledge_packs_list()
    assert res["ok"] is True
    assert isinstance(res["packs"], list) and res["packs"], "expected packs from registry.json"
    ids = [p["id"] for p in res["packs"]]
    assert "core" in ids
    core = next(p for p in res["packs"] if p["id"] == "core")
    assert core["always_on"] is True and core["enabled"] is True
    # core sorts first
    assert res["packs"][0]["id"] == "core"
    # presets bundle is exposed for the picker
    assert isinstance(res["presets"], dict) and "maker" in res["presets"]
    # every pack row carries the fields the UI needs
    for p in res["packs"]:
        assert {"id", "title", "summary", "approx_bytes", "doc_count", "enabled"} <= set(p)


class _FakeReq:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def test_post_rejects_empty_body():
    from routers.knowledge import knowledge_packs_set

    resp = asyncio.run(knowledge_packs_set(_FakeReq({})))
    # returns a JSONResponse with 400 on no packs/preset
    assert getattr(resp, "status_code", 200) == 400
