"""動画生成（MiniMax-Hailuo-02 ほか）。非同期タスク → ポーリング → ダウンロード。"""

from __future__ import annotations

import time
from pathlib import Path

from .api import MinimaxClient, MinimaxError
from .config import DEFAULT_VIDEO_MODEL, EP_VIDEO, EP_VIDEO_QUERY, VIDEO_MODEL_LIMITS
from .images import as_image_ref

TERMINAL_OK = {"Success"}
TERMINAL_NG = {"Fail"}


def validate(model: str, duration: int, resolution: str, has_first_frame: bool) -> None:
    limits = VIDEO_MODEL_LIMITS.get(model)
    if not limits:
        return  # 未知のモデルはそのまま送る（新モデル対応のため）
    if duration not in limits["durations"]:
        raise MinimaxError(
            f"{model} の duration は {limits['durations']} のみ対応です（指定: {duration}）"
        )
    if resolution not in limits["resolutions"]:
        raise MinimaxError(
            f"{model} の resolution は {limits['resolutions']} のみ対応です（指定: {resolution}）"
        )
    if (duration, resolution) in limits["invalid_combos"]:
        raise MinimaxError(f"{model} は duration={duration} と resolution={resolution} の組み合わせに非対応です")
    if has_first_frame and not limits["supports_first_frame"]:
        raise MinimaxError(f"{model} は first_frame_image に非対応です（I2V 系モデルを使ってください）")


def submit(
    client: MinimaxClient,
    prompt: str,
    *,
    model: str = DEFAULT_VIDEO_MODEL,
    duration: int = 6,
    resolution: str = "1080P",
    first_frame: str | None = None,
    prompt_optimizer: bool = True,
    force: bool = False,
) -> str:
    """生成タスクを投げて task_id を返す。"""
    if not force:
        validate(model, duration, resolution, bool(first_frame))

    body: dict = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "prompt_optimizer": prompt_optimizer,
    }
    if first_frame:
        # 出力アスペクト比は first_frame_image の比率に従う。
        # 9:16 / 4:5 の縦型広告では必ずキーフレームを先に作ること。
        body["first_frame_image"] = as_image_ref(first_frame)

    payload = client.request("POST", EP_VIDEO, body=body)
    if payload.get("_dry_run"):
        return "dry-run-task-id"
    task_id = payload.get("task_id")
    if not task_id:
        raise MinimaxError(f"task_id が返りませんでした: {payload}")
    return task_id


def query(client: MinimaxClient, task_id: str) -> dict:
    payload = client.request("GET", EP_VIDEO_QUERY, params={"task_id": task_id})
    if payload.get("_dry_run"):
        return {"status": "Success", "file_id": "dry-run-file-id"}
    return payload


def wait_for(
    client: MinimaxClient,
    task_id: str,
    *,
    interval: int = 10,
    timeout: int = 1800,
    on_tick=None,
) -> str:
    """完了まで待ち file_id を返す。"""
    started = time.time()
    while True:
        res = query(client, task_id)
        status = res.get("status", "Unknown")
        if on_tick:
            on_tick(status, int(time.time() - started))
        if status in TERMINAL_OK:
            file_id = res.get("file_id")
            if not file_id:
                raise MinimaxError(f"成功したが file_id がありません: {res}")
            return file_id
        if status in TERMINAL_NG:
            raise MinimaxError(f"生成失敗 task_id={task_id}: {res}")
        if time.time() - started > timeout:
            raise MinimaxError(f"タイムアウト（{timeout}s）task_id={task_id} status={status}")
        if client.dry_run:
            return "dry-run-file-id"
        time.sleep(interval)


def generate_and_save(
    client: MinimaxClient,
    prompt: str,
    dest: Path,
    *,
    interval: int = 10,
    timeout: int = 1800,
    quiet: bool = False,
    **kwargs,
) -> Path:
    task_id = submit(client, prompt, **kwargs)
    if not quiet:
        print(f"  task_id={task_id}")

    def tick(status: str, elapsed: int) -> None:
        if not quiet:
            print(f"  [{elapsed:>4}s] {status}")

    file_id = wait_for(client, task_id, interval=interval, timeout=timeout, on_tick=tick)
    url = client.file_download_url(file_id)
    return client.download(url, dest)
