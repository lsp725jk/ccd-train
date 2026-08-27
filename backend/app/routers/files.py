"""图像文件服务：按 image_id 返回原图（标注器/预览/画廊共用）。

带 ETag + Cache-Control：图像内容不变则浏览器直接复用缓存（304），
文件被替换（mtime 变化）时 ETag 自动失效。
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.db import get_conn

router = APIRouter()

_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
         "bmp": "image/bmp", "webp": "image/webp"}


def _etag(path: Path) -> str:
    st = path.stat()
    return f'"{st.st_size}-{st.st_mtime_ns}"'


@router.get("/images/{image_id}/file")
def image_file(image_id: int, request: Request):
    from app.engines.data_utils import image_path_of
    try:
        path = image_path_of(image_id)
    except ValueError:
        raise HTTPException(404, "图像不存在")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    etag = _etag(path)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)

    ext = path.suffix.lower().lstrip(".") or "png"
    return Response(
        content=path.read_bytes(),
        media_type=_MIME.get(ext, "application/octet-stream"),
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
