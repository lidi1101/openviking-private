import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import uuid
from email.utils import formatdate
import requests
import logging

logger = logging.getLogger(__name__)


def generate_signature(method, url, access_key, secret_key, date_str, signed_headers, headers, encode_uri_params=True):
    """
    生成 HMAC 签名
    """
    http_method = method.upper()
    parsed_url = urllib.parse.urlparse(url)
    http_uri = parsed_url.path or "/"

    canonical_query_string = ""
    if parsed_url.query:
        query_pairs = urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True)
        if encode_uri_params:
            query_pairs = [(urllib.parse.quote(k, safe=''), urllib.parse.quote(v, safe='')) for k, v in query_pairs]
        query_pairs.sort(key=lambda x: x[0])
        canonical_query_string = "&".join(f"{k}={v}" for k, v in query_pairs)

    signed_headers_string = ""
    for h in signed_headers:
        header_name = h.strip()
        if header_name.lower() in [k.lower() for k in headers.keys()]:
            for orig_key, value in headers.items():
                if orig_key.lower() == header_name.lower():
                    signed_headers_string += f"{orig_key}:{value}\n"
                    break
        else:
            signed_headers_string += "\n"

    signing_string = (
        f"{http_method}\n"
        f"{http_uri}\n"
        f"{canonical_query_string}\n"
        f"{access_key}\n"
        f"{date_str}\n"
        f"{signed_headers_string}"
    )

    hash_obj = hmac.new(secret_key.encode("utf-8"), signing_string.encode("utf-8"), hashlib.sha256)
    signature = base64.b64encode(hash_obj.digest()).decode("utf-8")

    return signature, signing_string


def send_emb_request(query_list):
    # 镜像/开发
    access_key = "pc-ai-agent"
    secret_key = "pcYOYOqazXSW123!@##@!$%^^%$"

    date_str = formatdate(usegmt=True)  # 动态时间
    url = "https://all-scenario-device-test.test.honor.com/all-scenario/rag/v1/get-embedding"  # 开发 内网
    method = "POST"
    # 请求头 (参与签名的必须在这里)
    headers = {
        "User-Agent": "curl/7.29.0",
    }

    signed_headers = ["User-Agent"]  # 按顺序

    signature, signing_string = generate_signature(
        method, url, access_key, secret_key, date_str, signed_headers, headers, encode_uri_params=True
    )

    # 发送请求
    full_headers = {
        "X-HMAC-SIGNATURE": signature,
        "X-HMAC-ALGORITHM": "hmac-sha256",
        "X-HMAC-ACCESS-KEY": access_key,
        "Date": date_str,
        "X-HMAC-SIGNED-HEADERS": ";".join(signed_headers),
        "Content-Type": "application/json",
        **headers
    }
    payload = {
        "query": query_list
    }

    with requests.post(url, json=payload, headers=full_headers, stream=True) as r:
        r.raise_for_status()  # 检查请求是否成功
        full_data = b""
        for chunk in r.iter_content(chunk_size=None):
            if chunk:
                full_data += chunk

    response_json = json.loads(full_data.decode("utf-8"))
    data = response_json.get("data")
    if isinstance(data, str):
        data = data.strip()
        if data.startswith("[") or data.startswith("["):
            data = json.loads(data)
        else:
            raise ValueError(f"data is not json string: {repr(data)}")

    if isinstance(data, list):
        embeddings = data[0]["embeddings"]
        return embeddings
    elif isinstance(data, dict):
        embeddings = data["embeddings"]
        return embeddings
    else:
        raise TypeError(f"unexpected data type: {type(data)}")


if __name__ == "__main__":
    for i in range(10):
        start_time = time.perf_counter()  # 记录开始时间
        result = send_emb_request(["你好"])
        print(result)