"""MiniMax API の HTTP レイヤ（標準ライブラリのみ、外部依存なし）。"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import STATUS_HINTS, Settings

USER_AGENT = "w12minimax/0.1 (+https://github.com/spenda-agency/w12minimax)"
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
RETRYABLE_STATUS = {1002, 1013, 1039, 1001}


class MinimaxError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        self.status_code = status_code
        self.payload = payload
        hint = STATUS_HINTS.get(status_code or -1)
        if hint:
            message = f"{message} — {hint}"
        super().__init__(message)


class MinimaxClient:
    def __init__(self, settings: Settings, *, dry_run: bool = False, verbose: bool = False):
        self.s = settings
        self.dry_run = dry_run
        self.verbose = verbose

    # ---------- 低レベル ----------

    def _headers(self, *, json_body: bool) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.s.api_key}", "User-Agent": USER_AGENT}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        params: dict | None = None,
        with_group_id: bool = False,
    ) -> dict:
        params = dict(params or {})
        if with_group_id and self.s.group_id:
            params.setdefault("GroupId", self.s.group_id)
        url = self.s.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        if self.dry_run:
            print(f"[dry-run] {method} {url}")
            if body is not None:
                print("[dry-run] body: " + json.dumps(body, ensure_ascii=False, indent=2))
            return {"_dry_run": True}

        if not self.s.api_key:
            raise MinimaxError("MINIMAX_API_KEY が未設定です。.env を作成してください（.env.example 参照）")

        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        last_err: Exception | None = None

        for attempt in range(self.s.max_retries + 1):
            req = urllib.request.Request(
                url, data=data, method=method, headers=self._headers(json_body=data is not None)
            )
            try:
                with urllib.request.urlopen(req, timeout=self.s.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
                self._raise_for_base_resp(payload)
                return payload
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:800]
                last_err = MinimaxError(f"HTTP {e.code} {method} {path}: {detail}")
                if e.code not in RETRYABLE_HTTP or attempt == self.s.max_retries:
                    raise last_err from e
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_err = MinimaxError(f"通信エラー {method} {path}: {e}")
                if attempt == self.s.max_retries:
                    raise last_err from e
            except MinimaxError as e:
                if e.status_code not in RETRYABLE_STATUS or attempt == self.s.max_retries:
                    raise
                last_err = e
            self._sleep_backoff(attempt)

        raise last_err or MinimaxError("不明なエラー")

    def _raise_for_base_resp(self, payload: dict) -> None:
        base = payload.get("base_resp") or {}
        code = base.get("status_code")
        if code not in (None, 0):
            raise MinimaxError(
                f"API エラー status_code={code}: {base.get('status_msg', '')}",
                status_code=code,
                payload=payload,
            )

    def _sleep_backoff(self, attempt: int) -> None:
        wait = min(2 ** attempt, 16) + random.uniform(0, 0.75)
        if self.verbose:
            print(f"  retry in {wait:.1f}s (attempt {attempt + 1})")
        time.sleep(wait)

    # ---------- ファイル ----------

    def file_download_url(self, file_id: str) -> str:
        payload = self.request(
            "GET", "/files/retrieve", params={"file_id": file_id}, with_group_id=True
        )
        if payload.get("_dry_run"):
            return "https://example.invalid/dry-run.mp4"
        url = (payload.get("file") or {}).get("download_url")
        if not url:
            raise MinimaxError(f"download_url を取得できませんでした: {payload}")
        return url

    def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            print(f"[dry-run] download {url} -> {dest}")
            dest.write_bytes(b"")
            return dest
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(self.s.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.s.timeout) as resp, dest.open("wb") as f:
                    while chunk := resp.read(1 << 16):
                        f.write(chunk)
                return dest
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == self.s.max_retries:
                    raise MinimaxError(f"ダウンロード失敗 {url}: {e}") from e
                self._sleep_backoff(attempt)
        return dest
