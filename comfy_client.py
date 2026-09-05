"""
ComfyUI API client — Method 2: WebSocket + History (Monitor Completion)

用法：輸入 0~3 張圖片 + 一段提示詞 → 輸出一張圖片（0 張 = 純文生圖）

  python comfy_client.py [--image1 <圖1>] [--image2 <圖2>] [--image3 <圖3>] --prompt "提示詞" [--width W] [--height H] [--seed -1] [--output out.png]

  --image1 / --image2 / --image3 解析順序（從專案目錄執行）：
    1. 本機路徑（相對或絕對），例：input/sofa.png 或 C:/path/sofa.png → 自動上傳
    2. 專案 input/ 資料夾：--image1 sofa.png 會找 input/sofa.png → 自動上傳
    3. 已存在 ComfyUI input/ 的檔名；三者都沒有會報錯

  依輸入的圖片數量自動選擇 workflow：
    0 張 → image_qwen_Image_2512(no_image).json（純文生圖）
    1 張 → image_qwen_image_edit_2511(input_image1).json
    2 張 → image_qwen_image_edit_2511(input_image2).json
    3 張 → image_qwen_image_edit_2511(input_image3).json

  --width / --height（選用）：輸出解析度。省略時：有第一張圖=跟它一致；沒有圖（純文生圖）=1024x1024
  提示詞：純文生圖時是生成描述；有圖片時說明「如何用其餘圖片去處理圖1」。
  例：--prompt "把圖1中的皮革沙發材質，替換成圖2中的毛皮材質"
"""
import argparse
import json
import os
import random
import struct
import time
import uuid
from pathlib import Path

import requests
import websocket  # pip install websocket-client

# ===== 伺服器設定 =====
# ComfyUI 伺服器位址：可從環境變數 COMFYUI_BASE_URL 讀取，未設定時用預設值
HTTP_BASE = os.environ.get("COMFYUI_BASE_URL", "http://localhost:8188").rstrip("/")
WS_BASE = HTTP_BASE.replace("http://", "ws://").replace("https://", "wss://")

WORKFLOW_CONFIG = {
    0: dict(
        file=Path("image_qwen_Image_2512(no_image).json"),
        prompt_node="238:227", prompt_field="text",
        ksampler="238:230",
        load_nodes=[],
        size_node="238:232",
    ),
    1: dict(
        file=Path("image_qwen_image_edit_2511(input_image1).json"),
        prompt_node="170:151", prompt_field="prompt",
        ksampler="170:169",
        load_nodes=["41"],
        size_node=None,
    ),
    2: dict(
        file=Path("image_qwen_image_edit_2511(input_image2).json"),
        prompt_node="170:151", prompt_field="prompt",
        ksampler="170:169",
        load_nodes=["41", "83"],
        size_node=None,
    ),
    3: dict(
        file=Path("image_qwen_image_edit_2511(input_image3).json"),
        prompt_node="170:151", prompt_field="prompt",
        ksampler="170:169",
        load_nodes=["41", "83", "196"],
        size_node=None,
    ),
}
LOCAL_INPUT_DIR = Path("input")  # 專案裡的 input/ 資料夾
OUTPUT_DIR = Path("output")

# ===== 各 workflow 的節點 id（於 WORKFLOW_CONFIG 中引用）=====
# 文生圖 no_image：CLIPTextEncode 正向=238:227、KSampler=238:230
# 編輯 input_image1/2/3：TextEncodeQwenImageEditPlus=170:151、KSampler=170:169
# LoadImage：圖片1=41、圖片2=83、圖片3=196（僅 input_image3 workflow 有）

SEED_MAX = 2 ** 32 - 1  # 隨機種子上限（落在 min=0 ~ max 內）


def remote_image_exists(name: str) -> bool:
    """檢查該檔名是否已存在 ComfyUI 的 input/ 資料夾。"""
    r = requests.get(f"{HTTP_BASE}/view", params={"filename": name, "subfolder": "", "type": "input"})
    return r.status_code == 200


def find_local_image(value: str) -> Path:
    """回傳本機圖片路徑：先試原路徑，再試專案 input/ 資料夾；找不到回 None。"""
    p = Path(value)
    if p.is_file():
        return p
    candidate = LOCAL_INPUT_DIR / p.name
    if candidate.is_file():
        return candidate
    return None


def upload_image(name: str, local_path: Path) -> str:
    """上傳本機圖片到 ComfyUI input/，回傳可用於 LoadImage 的檔名。"""
    with open(local_path, "rb") as f:
        r = requests.post(
            f"{HTTP_BASE}/upload/image",
            files={"image": (name, f, "image/png")},
            data={"overwrite": "true", "subfolder": ""},
        )
    r.raise_for_status()
    res = r.json()
    print(f"上傳 {local_path} -> {res.get('name')}")
    return res.get("name", name)


def resolve_image(value: str) -> str:
    """本機有的就上傳；否則檢查 server 上是否有此檔名，沒有就給清楚的錯誤。"""
    local = find_local_image(value)
    if local is not None:
        return upload_image(local.name, local)
    name = Path(value).name
    if not remote_image_exists(name):
        raise SystemExit(
            f"找不到圖片 {name}：請確認 {value} 或 {LOCAL_INPUT_DIR}/{name} 存在（讓腳本上傳），"
            f"或先把它放進 ComfyUI 的 input/ 資料夾"
        )
    print(f"使用既有 input 檔：{name}")
    return name


def fetch_image(img: dict) -> bytes:
    url = (
        f"{HTTP_BASE}/view?filename={img['filename']}"
        f"&subfolder={img.get('subfolder', '')}&type={img.get('type', 'output')}"
    )
    r = requests.get(url)
    r.raise_for_status()
    return r.content


def fetch_image_bytes(name: str, img_type: str = "input") -> bytes:
    """從 ComfyUI 抓回圖片 bytes（預設 input/ 資料夾）。"""
    r = requests.get(f"{HTTP_BASE}/view", params={"filename": name, "subfolder": "", "type": img_type})
    r.raise_for_status()
    return r.content


def _image_size_from_bytes(data: bytes):
    """從圖片 bytes 解析 (width, height)；解析不到回 None。支援 PNG/JPEG/WebP/GIF/BMP。"""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"BM":
            w, h = struct.unpack("<ii", data[18:26])
            return w, abs(h)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8X":
                w = 1 + (data[24] | (data[25] << 8) | (data[26] << 16))
                h = 1 + (data[27] | (data[28] << 8) | (data[29] << 16))
                return w, h
            if data[12:16] == b"VP8L":
                w = 1 + (((data[22] & 0x3F) << 8) | data[21])
                h = 1 + (((data[24] & 0x0F) << 10) | (data[23] << 2) | ((data[22] & 0xC0) >> 6))
                return w, h
            if data[12:16] == b"VP8 ":
                w = 1 + ((data[26] | (data[27] << 8)) & 0x3FFF)
                h = 1 + ((data[28] | (data[29] << 8)) & 0x3FFF)
                return w, h
        if data[:2] == b"\xff\xd8":
            i, n = 2, len(data)
            while i + 9 < n:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD9:
                    i += 2
                    continue
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    except (struct.error, IndexError):
        pass
    return None


def image_dimensions(value: str):
    """回傳 (width, height)；讀不到時回 (None, None)。先試本機，再試 ComfyUI input/。"""
    local = find_local_image(value)
    if local is not None:
        size = _image_size_from_bytes(local.read_bytes())
        if size:
            return size
    name = Path(value).name
    try:
        if remote_image_exists(name):
            size = _image_size_from_bytes(fetch_image_bytes(name, "input"))
            if size:
                return size
    except requests.RequestException:
        pass
    return None, None


def parse_args():
    parser = argparse.ArgumentParser(
        description="輸入 0~3 張圖片 + 一段提示詞，用 ComfyUI 輸出一張圖片（0 張=純文生圖）"
    )
    parser.add_argument("--image1", default=None, help="圖片1：本機路徑或 ComfyUI 檔名（主要被編輯的圖；省略=純文生圖）")
    parser.add_argument("--image2", default=None, help="圖片2：本機路徑或 ComfyUI 檔名（參考／材質圖，選用）")
    parser.add_argument("--image3", default=None, help="圖片3：本機路徑或 ComfyUI 檔名（參考圖，選用）")
    parser.add_argument("--width", type=int, default=None, help="輸出寬度；省略=第一張圖寬度（無圖時 1024）")
    parser.add_argument("--height", type=int, default=None, help="輸出高度；省略=第一張圖高度（無圖時 1024）")
    parser.add_argument("--prompt", required=True, help="提示詞：說明如何用其餘圖片處理圖1（必要）")
    parser.add_argument("--seed", type=int, default=-1, help="隨機種子；負數或省略=隨機")
    parser.add_argument("--output", default=None, help="輸出檔名/路徑（預設 output/時間戳.png）")
    return parser.parse_args()


def main():
    args = parse_args()

    # 累積順序檢查：提供較後的圖時，前面的圖也必須提供
    if args.image2 is not None and args.image1 is None:
        raise SystemExit("提供 --image2 時也必須提供 --image1（workflow 為累積式）")
    if args.image3 is not None and (args.image1 is None or args.image2 is None):
        raise SystemExit("提供 --image3 時也必須提供 --image1 與 --image2（workflow 為累積式）")

    image_count = sum(v is not None for v in (args.image1, args.image2, args.image3))

    cfg = WORKFLOW_CONFIG[image_count]
    if not cfg["file"].is_file():
        raise SystemExit(f"找不到 workflow 檔案：{cfg['file']}")

    with open(cfg["file"], encoding="utf-8") as f:
        prompt = json.load(f)

    input_images = [resolve_image(v) for v in (args.image1, args.image2, args.image3) if v is not None]
    seed = args.seed if args.seed >= 0 else random.randint(0, SEED_MAX)

    # 預設輸出解析度：有第一張圖=跟它一致；沒有（純文生圖）=1024x1024
    if args.image1 is not None:
        dw, dh = image_dimensions(args.image1)
        width_default, height_default = dw or 1024, dh or 1024
    else:
        width_default = height_default = 1024
    width = args.width if args.width is not None else width_default
    height = args.height if args.height is not None else height_default

    for node_id, img in zip(cfg["load_nodes"], input_images):
        prompt[node_id]["inputs"]["image"] = img

    prompt[cfg["prompt_node"]]["inputs"][cfg["prompt_field"]] = args.prompt
    prompt[cfg["ksampler"]]["inputs"]["seed"] = seed

    if cfg["size_node"] is not None:
        prompt[cfg["size_node"]]["inputs"]["width"] = width
        prompt[cfg["size_node"]]["inputs"]["height"] = height
        size_str = f"{width}x{height}"
    else:
        size_str = f"{width}x{height}（編輯輸出實際跟隨輸入圖）"
    print(f"workflow={cfg['file'].name}, 圖片={input_images}, size={size_str}, seed={seed}")

    client_id = str(uuid.uuid4())
    state = {"prompt_id": None, "done": False, "error": None}

    def on_message(ws, message):
        if not message:
            return
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            return
        mtype = msg.get("type")
        data = msg.get("data", {})
        if mtype == "progress":
            print(f"  進度 {data.get('value')}/{data.get('max')}")
        elif mtype == "executing":
            # node 為 null 代表該 prompt_id 執行結束
            if data.get("node") is None and data.get("prompt_id") == state["prompt_id"]:
                state["done"] = True
                ws.close()
        elif mtype == "exec_error":
            state["error"] = data.get("exception_message", "unknown")
            state["done"] = True
            ws.close()

    def on_open(ws):
        print("WebSocket 已連線，開始 queue workflow …")
        r = requests.post(
            f"{HTTP_BASE}/prompt",
            json={"prompt": prompt, "client_id": client_id},
        )
        if r.status_code != 200:
            state["error"] = r.text
            state["done"] = True
            ws.close()
            return
        res = r.json()
        state["prompt_id"] = res.get("prompt_id")
        print("prompt_id =", state["prompt_id"], " queue number =", res.get("number"))

    ws_url = f"{WS_BASE}/ws?clientId={client_id}"
    print("連線中:", ws_url)
    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
    ws.run_forever(ping_interval=20)

    if state["error"]:
        raise SystemExit("執行錯誤: " + state["error"])
    if not state["done"]:
        raise SystemExit("未完成就斷線了")

    # 取得歷史（加 retry 防競態：WS 完成事件先於 history 寫入的情況）
    entry = {}
    for _ in range(10):
        hist = requests.get(f"{HTTP_BASE}/history/{state['prompt_id']}").json()
        entry = hist.get(state["prompt_id"]) or {}
        if entry.get("outputs"):
            break
        time.sleep(0.5)

    images = []
    for out in entry.get("outputs", {}).values():
        for img in out.get("images", []):
            images.append(img)
    if not images:
        raise SystemExit("history 沒有輸出圖片。若無結果，可把 PreviewImage 節點改成 SaveImage。")

    # 輸出「一張」圖片
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = OUTPUT_DIR / (time.strftime("%Y%m%d_%H%M%S") + ".png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(fetch_image(images[0]))
    print("輸出圖片:", out_path)

    for extra in images[1:]:
        OUTPUT_DIR.mkdir(exist_ok=True)
        extra_path = OUTPUT_DIR / extra["filename"]
        extra_path.write_bytes(fetch_image(extra))
        print("額外輸出:", extra_path)


if __name__ == "__main__":
    main()
