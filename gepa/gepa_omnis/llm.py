"""OpenAI-compatible chat client for the gateway (stdlib only)."""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


class Chat:
    """A GEPA LanguageModel: `chat(prompt) -> str`. Records its cost in the ledger."""

    def __init__(self, model_id, base_url, api_key, ledger=None, prices=(0.0, 0.0),
                 kind="reflection", timeout=300):
        self.model_id, self.base_url, self.api_key = model_id, base_url.rstrip("/"), api_key
        self.ledger, self.prices, self.kind, self.timeout = ledger, prices, kind, timeout

    def __call__(self, prompt):
        msgs = prompt if isinstance(prompt, list) else [{"role": "user", "content": prompt}]
        body = json.dumps({"model": self.model_id, "messages": msgs, "temperature": 1.0}).encode()
        for attempt in range(3):
            req = urllib.request.Request(self.base_url + "/chat/completions", data=body, headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        u = data.get("usage") or {}
        if self.ledger is not None:
            cost = (u.get("prompt_tokens", 0) * self.prices[0]
                    + u.get("completion_tokens", 0) * self.prices[1]) / 1e6
            self.ledger.add(cost, self.kind)
        return data["choices"][0]["message"].get("content") or ""


def from_omnis(omnis_src, ref, ledger=None, kind="reflection"):
    models = json.loads((Path(omnis_src) / "config" / "models.json").read_text(encoding="utf-8"))
    m = models["models"][ref]
    prices = (m.get("input_token_price_per_million", 0.0), m.get("output_token_price_per_million", 0.0))
    return Chat(m["model"], os.environ["OPENAI_BASE_URL"], os.environ["OPENAI_API_KEY"],
                ledger, prices, kind)
