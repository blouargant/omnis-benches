"""Endpoint metadata side information (model listing, LiteLLM model info)."""

from core import check, Result, INFO, WARN


@check("Model listing (/models)", category="meta", critical=False,
       why="Omnis's web UI lists provider models via GET /models (the model picker).")
def model_listing(client):
    code, obj = client.get_json("/models")
    if code != 200 or not isinstance(obj, dict):
        return Result(WARN, "/models returned %s" % code, data={"body": str(obj)[:200]})
    ids = [m.get("id") for m in (obj.get("data") or []) if isinstance(m, dict)]
    present = client.model in ids
    return Result(INFO if present else WARN,
                  "%d models listed; '%s' %s" % (len(ids), client.model, "present" if present else "NOT in list"),
                  data={"present": present, "count": len(ids)})


@check("LiteLLM model info (/model/info)", category="meta", critical=False,
       why="Omnis prefills context length / pricing / embedding dim from LiteLLM's /model/info.")
def model_info(client):
    code, obj = client.get_json("/model/info")
    if code != 200 or not isinstance(obj, dict):
        return Result(INFO, "no /model/info (not a LiteLLM gateway)")
    rows = obj.get("data") or []
    mine = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("model_name") or (row.get("litellm_params") or {}).get("model")
        if name == client.model:
            mine = row
            break
    if not mine:
        return Result(INFO, "LiteLLM /model/info present (%d models) but no exact match for '%s'"
                      % (len(rows), client.model))
    info = mine.get("model_info") or {}
    return Result(INFO, "LiteLLM metadata: ctx=%s in=%s out=%s mode=%s" % (
        info.get("max_input_tokens"),
        info.get("input_cost_per_token"),
        info.get("output_cost_per_token"),
        info.get("mode")), data={"model_info": info})
