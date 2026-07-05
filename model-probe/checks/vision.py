"""Vision / multimodal image-input checks (opt-in: only runs with --vision).

Omnis attaches images to a turn as `image_url` content parts (from InlineData).
This is a capability probe: does the endpoint accept multimodal content without
erroring? (We send a 1x1 image, so we check acceptance, not description quality.)
"""

from core import check, Result, PASS, FAIL, WARN

# 1x1 PNG (single magenta pixel) as a data URL.
_PIXEL = ("data:image/png;base64,"
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@check("Image input (vision)", category="vision", critical=True,
       why="Omnis can attach images (InlineData -> image_url); the endpoint must accept multimodal content.")
def image_input(client):
    content = [
        {"type": "text", "text": "Describe this image in one short sentence."},
        {"type": "image_url", "image_url": {"url": _PIXEL}},
    ]
    r = client.chat(messages=[{"role": "user", "content": content}], stream=False)
    if not r.ok:
        return Result(FAIL, "endpoint rejected image content (status=%s): %s"
                      % (r.status_code, (r.error or "")[:300]))
    if r.text.strip():
        return Result(PASS, "multimodal content accepted; answer: %r" % r.text[:80])
    return Result(WARN, "image content accepted but empty answer")
