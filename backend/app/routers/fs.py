"""服务器文件系统浏览（目录选择器用，只读，不暴露文件内容）。"""
import os
import string
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/fs/drives")
def list_drives():
    """Windows 可用盘符列表。"""
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.isdir(f"{d}:\\")]


@router.get("/fs/list")
def list_dir(path: str = ""):
    """列目录（仅子目录名）。"""
    if not path:
        raise HTTPException(400, "缺少路径")
    p = Path(path)
    if not p.is_dir():
        raise HTTPException(400, f"目录不存在：{path}")
    try:
        dirs = sorted(
            e.name for e in os.scandir(p)
            if e.is_dir() and not e.name.startswith(".")
        )
    except PermissionError:
        raise HTTPException(403, f"无权限访问：{path}")
    parent = str(p.parent) if p.parent != p else ""
    return {"path": str(p), "parent": parent, "dirs": dirs, "name": p.name or p.root}
