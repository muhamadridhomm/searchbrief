"""Optional image search and user-keyed image generation."""

from __future__ import annotations

import html
import json
import re
import time
import mimetypes
import base64
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
GEMINI_IMAGE_URL = "https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash-image:generateContent"


class ImageServiceError(RuntimeError):
    pass


def generate_comfy_image(prompt: str, base_url: str, workflow: dict, prompt_node_id: str, *, request=None, sleep=time.sleep, timeout=180) -> dict:
    """Submit a ComfyUI API-format workflow, set its positive prompt, and return the first image."""
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ImageServiceError("ComfyUI must be configured with a localhost address, such as http://127.0.0.1:8188.")
    graph = json.loads(json.dumps(workflow))
    node = graph.get(str(prompt_node_id))
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict) or "text" not in node["inputs"]:
        raise ImageServiceError("The selected ComfyUI node ID does not have a text input. Use an API-format workflow and choose its positive CLIP Text Encode node.")
    node["inputs"]["text"] = prompt
    base = base_url.rstrip("/")
    do_request = request or _comfy_request
    try:
        queued = do_request(base + "/prompt", {"prompt": graph}, "POST")
        prompt_id = queued.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ImageServiceError("ComfyUI did not return a prompt ID. Check that the workflow uses API format.")
        deadline = time.monotonic() + timeout
        history = {}
        while time.monotonic() < deadline:
            sleep(1)
            history = do_request(base + "/history/" + prompt_id, None, "GET")
            entry = history.get(prompt_id, {}) if isinstance(history, dict) else {}
            outputs = entry.get("outputs", {}) if isinstance(entry, dict) else {}
            images = [image for output in outputs.values() for image in output.get("images", []) if isinstance(output, dict)]
            if images:
                item = images[0]
                query = urlencode({"filename": item.get("filename", ""), "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
                raw, content_type = _comfy_request(base + "/view?" + query, None, "GET", raw=True)
                if len(raw) > 8_000_000:
                    raise ImageServiceError("The ComfyUI image is too large for this local draft.")
                mime = content_type.split(";", 1)[0] if content_type else mimetypes.guess_type(item.get("filename", ""))[0] or "image/png"
                data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
                return {"kind": "generated", "provider": "ComfyUI (local)", "prompt": prompt, "url": data_url, "preview_url": data_url}
        raise ImageServiceError("ComfyUI did not finish before the 3-minute timeout. Check its queue and try again.")
    except ImageServiceError:
        raise
    except Exception as exc:
        raise ImageServiceError("Could not reach ComfyUI. Check that it is running and that its API is enabled.") from exc


def _comfy_request(url: str, body: dict | None, method: str, *, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    with urlopen(req, timeout=20) as response:
        content = response.read()
        return (content, response.headers.get("Content-Type", "")) if raw else json.loads(content.decode("utf-8"))


def plain(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", value or ""))).strip()


def search_images(query: str, *, fetch=None) -> list[dict]:
    fetch = fetch or _fetch_commons
    params = urlencode({"action": "query", "generator": "search", "gsrsearch": query, "gsrnamespace": 6,
                        "gsrlimit": 20, "prop": "imageinfo", "iiprop": "url|mime|extmetadata", "iiurlwidth": 600,
                        "format": "json", "formatversion": 2})
    data = fetch(f"{COMMONS_API}?{params}")
    terms = {word for word in re.findall(r"[a-z0-9]+", query.casefold()) if len(word) > 2}
    results = []
    for page in data.get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [{}])[0]
        metadata = info.get("extmetadata") or {}
        get = lambda key: plain((metadata.get(key) or {}).get("value", ""))
        description = get("ImageDescription")
        searchable = f"{page.get('title', '')} {description}".casefold()
        title_terms = set(re.findall(r"[a-z0-9]+", page.get("title", "").casefold()))
        matched_title = len(terms & title_terms)
        matched_description = len(terms & set(re.findall(r"[a-z0-9]+", searchable)))
        if len(terms) >= 2 and matched_title == 0 and matched_description < 2:
            continue
        image_url = info.get("url", "")
        page_url = info.get("descriptionurl", "")
        if not image_url.startswith("https://") or not page_url.startswith("https://") or not info.get("mime", "").startswith("image/"):
            continue
        results.append({"title": page.get("title", ""), "description": description[:500], "url": image_url, "preview_url": info.get("thumburl") or image_url,
                        "page_url": page_url, "creator": get("Artist") or get("Attribution"),
                        "license": get("LicenseShortName") or "License not listed", "license_url": get("LicenseUrl"),
                        "provider": "Wikimedia Commons", "kind": "searched", "_relevance": matched_title * 3 + matched_description})
    results = sorted(results, key=lambda item: item.pop("_relevance", 0), reverse=True)
    return results[:8]


def _fetch_commons(url: str) -> dict:
    try:
        with urlopen(Request(url, headers={"User-Agent": "SearchBriefLocal/0.1", "Accept": "application/json"}), timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise ImageServiceError("Wikimedia Commons image search is unavailable. Try again later.") from exc


def generate_image(prompt: str, api_key: str, *, post=None) -> dict:
    post = post or _post_gemini
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["IMAGE"]}}
    data = post(body, api_key)
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            blob = part.get("inlineData") or part.get("inline_data") or {}
            mime = blob.get("mimeType") or blob.get("mime_type")
            encoded = blob.get("data")
            if mime in ("image/png", "image/jpeg", "image/webp") and encoded:
                if len(encoded) > 8_000_000:
                    raise ImageServiceError("The generated image is too large for this local draft. Try a smaller image.")
                return {"kind": "generated", "provider": "Gemini 2.5 Flash Image", "prompt": prompt,
                        "url": f"data:{mime};base64,{encoded}", "preview_url": f"data:{mime};base64,{encoded}"}
    raise ImageServiceError("The image provider returned no usable image. Check the prompt and try again.")


def _post_gemini(body: dict, api_key: str) -> dict:
    request = Request(GEMINI_IMAGE_URL, data=json.dumps(body).encode(), method="POST",
                      headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=90) as response:
            return json.load(response)
    except HTTPError as exc:
        raise ImageServiceError(f"Gemini image request failed (HTTP {exc.code}). Check your key, model access, and quota.") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise ImageServiceError("Could not reach the Gemini image service. Try again when online.") from exc
