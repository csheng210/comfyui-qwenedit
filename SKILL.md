---
name: comfyui-qwen-image-gen
description: Generate or edit images via the local ComfyUI Qwen Image 2.1 server using comfyui_qwen_image_client.py. Covers text-to-image, single-image editing, and 2-3 image composition. Use for image generation or editing requests in the comfyui-qwenedit project.
---

# ComfyUI Qwen Image Generation

Drive the local ComfyUI Qwen Image 2.1 server through `comfyui_qwen_image_client.py` to produce an image: queue a workflow, wait for completion over WebSocket, then download the result.

## Prerequisites
- Run from the current skill folder containing `comfyui_qwen_image_client.py`, the `1text_to_image.json` / `1image_to_image.json` / `2image_to_image.json` / `3image_to_image.json` workflows, and `input/` + `output/`. The script resolves paths relative to the current directory.
- Interpreter (project virtualenv): Windows `.venv\Scripts\python.exe`; POSIX `.venv/bin/python`.
- The ComfyUI server must be reachable. Base URL = `COMFYUI_BASE_URL` env var.

## How it works
The workflow is chosen by the number of input images, then prompt/seed/size/images are filled in and one image is returned:

| Images | Workflow | Mode |
|---|---|---|
| 0 | `1text_to_image.json` | text-to-image |
| 1 | `1image_to_image.json` | single-image edit |
| 2 | `2image_to_image.json` | 2-image composition |
| 3 | `3image_to_image.json` | 3-image composition |

Images are ordered and cumulative: `--image2` needs `--image1`; `--image3` needs `--image1` + `--image2`. No images = text-to-image.

Image binding is slot-based: `--imageN` maps to the `images.image_N` input of the Qwen image-encode node. Missing LoadImage slots in a workflow JSON are created automatically by the script.

## Output location
Default output lands in the project root `output/` folder, which is usually outside the Codex app workspace and therefore NOT displayable in chat.
When running from the Codex app, always pass `--output` as an absolute path under the current workspace `output/` folder (session CWD). The parent folder is created automatically.
After generation, show the result to the user with a Markdown image tag using the absolute output path.

## Usage
Text-to-image:
```
.venv\Scripts\python.exe comfyui_qwen_image_client.py --prompt "a red leather sofa, studio lighting" --width 1024 --height 1024 --output WORKSPACE\output\sofa.png
```

Single image (edit image 1):
```
.venv\Scripts\python.exe comfyui_qwen_image_client.py --image1 sofa.png --prompt "change the sofa material to fur"
```

Two images (image 2 is a reference for image 1):
```
.venv\Scripts\python.exe comfyui_qwen_image_client.py --image1 sofa.png --image2 fur.png --prompt "replace the leather in image 1 with the fur texture in image 2"
```

Three images:
```
.venv\Scripts\python.exe comfyui_qwen_image_client.py --image1 a.png --image2 b.png --image3 c.png --prompt "combine these as described"
```

## Arguments
| Flag | Required | Meaning |
|---|---|---|
| `--prompt` | yes | Text-to-image: generation description. Editing: how to use the other image(s) to process image 1. |
| `--image1` | no | Primary image (what is produced/edited from). Omit all images for text-to-image. |
| `--image2`, `--image3` | no | Extra reference images (cumulative order). |
| `--width`, `--height` | no | Output size (text-to-image only; default 1024x1024). With images, output follows the first input image. |
| `--seed` | no | Seed; negative or omitted = random. |
| `--output` | no | Output path; default `output/<timestamp>.png`. |

Size: width/height are written into the text-to-image latent node, so they apply there. The edit workflows have no size node - their output resolution follows the first input image (the printed size is informational then).

Input image resolution: for each `--imageN`, try (1) a local path (relative/absolute) then upload, (2) a file in `input/` then upload, (3) a file already on the server `input/` used as-is; otherwise it errors out.

## Output
The main result is saved to `--output` (preferred: under the current workspace `output/` so it displays in the Codex app) or the project root's `output/<timestamp>.png`; any extra saved images always go under the project root's `output/`. The last printed "輸出圖片:" path is the main result.

## Troubleshooting
- `找不到 workflow 檔案` - not run from the project root (workflow JSONs not found by filename).
- `找不到圖片 ...` - the image path/filename was not found locally, in `input/`, or on the server.
- Connection / WebSocket errors - check `COMFYUI_BASE_URL` and that the ComfyUI server is running and reachable.
