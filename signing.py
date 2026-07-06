"""VMOS Cloud API client with HMAC-SHA256 request signing.

Extracted from a.py so the monitor can import it without side effects.
All credentials come from environment variables.
"""
import binascii
import datetime
import hashlib
import hmac
import json
import os
import time

import requests

HOST = os.environ.get("VMOS_HOST", "api.vmoscloud.com")
BASE_URL = f"https://{HOST}"
ACCESS_KEY = os.environ.get("VMOS_ACCESS_KEY", "")
SECRET_KEY = os.environ.get("VMOS_SECRET_KEY", "")

if not ACCESS_KEY or not SECRET_KEY:
    raise RuntimeError(
        "VMOS_ACCESS_KEY and VMOS_SECRET_KEY must be set in the environment."
    )


def _get_signature(data, x_date, host, content_type, signed_headers, sk):
    json_string = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    x_content_sha256 = hashlib.sha256(json_string.encode("utf-8")).hexdigest()

    canonical_string = (
        f"host:{host}\n"
        f"x-date:{x_date}\n"
        f"content-type:{content_type}\n"
        f"signedHeaders:{signed_headers}\n"
        f"x-content-sha256:{x_content_sha256}"
    )

    short_x_date = x_date[:8]
    service = "armcloud-paas"
    credential_scope = f"{short_x_date}/{service}/request"
    algorithm = "HMAC-SHA256"

    hash_sha256 = hashlib.sha256(canonical_string.encode("utf-8")).hexdigest()
    string_to_sign = f"{algorithm}\n{x_date}\n{credential_scope}\n{hash_sha256}"

    k_date = hmac.new(sk.encode("utf-8"), short_x_date.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_date, service.encode("utf-8"), hashlib.sha256).digest()
    signing_key = hmac.new(k_service, b"request", hashlib.sha256).digest()

    signature_bytes = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    return binascii.hexlify(signature_bytes).decode()


def execute_authenticated_request(uri, data, timeout=30):
    url = f"{BASE_URL}{uri}"
    x_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    content_type = "application/json;charset=UTF-8"
    signed_headers = "content-type;host;x-content-sha256;x-date"

    signature = _get_signature(data, x_date, HOST, content_type, signed_headers, SECRET_KEY)

    headers = {
        "content-type": content_type,
        "x-date": x_date,
        "x-host": HOST,
        "authorization": (
            f"HMAC-SHA256 Credential={ACCESS_KEY}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }

    payload_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    response = requests.post(url, headers=headers, data=payload_str.encode("utf-8"), timeout=timeout)
    return response.json()


def take_screenshot(pad_codes, rotation=0, definition=50, height=1920, width=1080):
    uri = "/vcpcloud/api/padApi/screenshot"
    payload = {
        "padCodes": pad_codes,
        "rotation": rotation,
        "broadcast": False,
        "definition": definition,
        "resolutionHeight": height,
        "resolutionWidth": width,
    }
    return execute_authenticated_request(uri, payload)


def generate_preview_image(pad_codes, fmt="png"):
    uri = "/vcpcloud/api/padApi/generatePreview"
    payload = {"padCodes": pad_codes, "format": fmt}
    return execute_authenticated_request(uri, payload)


def fetch_screenshot(pad_codes, save_dir="screenshots", fmt="png", settle_seconds=2):
    """Trigger a screenshot, wait for render, download the image.

    Returns a list of dicts: [{"pad_code": str, "filepath": str|None, "error": str|None}]
    """
    if isinstance(pad_codes, str):
        pad_codes = [pad_codes]

    shot_resp = take_screenshot(pad_codes)
    if shot_resp.get("code") != 200:
        return [{"pad_code": c, "filepath": None, "error": shot_resp.get("msg", str(shot_resp))} for c in pad_codes]

    time.sleep(settle_seconds)

    preview_resp = generate_preview_image(pad_codes, fmt=fmt)
    if preview_resp.get("code") != 200:
        return [{"pad_code": c, "filepath": None, "error": preview_resp.get("msg", str(preview_resp))} for c in pad_codes]

    os.makedirs(save_dir, exist_ok=True)
    results = []
    for item in preview_resp.get("data", []):
        pad_code = item.get("padCode")
        if not item.get("success") or not item.get("accessUrl"):
            results.append({"pad_code": pad_code, "filepath": None, "error": item.get("reason", "no accessUrl")})
            continue
        img_resp = requests.get(item["accessUrl"], timeout=30)
        img_resp.raise_for_status()
        filename = f"{pad_code}_{int(time.time())}.{fmt}"
        filepath = os.path.join(save_dir, filename)
        with open(filepath, "wb") as f:
            f.write(img_resp.content)
        results.append({"pad_code": pad_code, "filepath": filepath, "error": None})
    return results
