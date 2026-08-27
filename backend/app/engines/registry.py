"""引擎注册表：内置引擎声明 + plugins/engines 自动发现。

添加新引擎两种方式：
1. 在 BUILTIN_ENGINES 加一行（{id: {module, task_type, label, defaults}}）
2. 或创建 plugins/engines/{name}/engine.json：
   {"id": "my_engine", "module": "my_package.my_engine", "task_type": "detect",
    "label": "My Engine", "defaults": {"epochs": 100, "imgsz": 640, "batch": 16}}
前端通过 /api/engines 自动获取配置，无需改前端。
"""
import json

from app.config import PLUGINS_DIR

BUILTIN_ENGINES = {
    "yolo11n": {"module": "app.engines.yolo_detect", "task_type": "detect", "label": "YOLO11n",
                "defaults": {"epochs": 100, "imgsz": 640, "batch": 16}},
    "yolo11s": {"module": "app.engines.yolo_detect", "task_type": "detect", "label": "YOLO11s",
                "defaults": {"epochs": 100, "imgsz": 640, "batch": 16}},
    "yolo11m": {"module": "app.engines.yolo_detect", "task_type": "detect", "label": "YOLO11m",
                "defaults": {"epochs": 100, "imgsz": 640, "batch": 12}},
    "yolo11n-cls": {"module": "app.engines.yolo_classify", "task_type": "classify", "label": "YOLO11n 分类",
                    "defaults": {"epochs": 50, "imgsz": 224, "batch": 32}},
    "yolo11s-cls": {"module": "app.engines.yolo_classify", "task_type": "classify", "label": "YOLO11s 分类",
                    "defaults": {"epochs": 50, "imgsz": 224, "batch": 32}},
    "unet_resnet18": {"module": "app.engines.smp_segment", "task_type": "segment", "label": "UNet-ResNet18",
                      "defaults": {"epochs": 60, "imgsz": 256, "batch": 8}},
    "unet_resnet50": {"module": "app.engines.smp_segment", "task_type": "segment", "label": "UNet-ResNet50",
                      "defaults": {"epochs": 60, "imgsz": 256, "batch": 6}},
    "deeplabv3p_resnet50": {"module": "app.engines.smp_segment", "task_type": "segment", "label": "DeepLabV3+ ResNet50",
                            "defaults": {"epochs": 60, "imgsz": 256, "batch": 6}},
    "patchcore": {"module": "app.engines.anomaly", "task_type": "us_segment", "label": "PatchCore 异常检测",
                  "defaults": {"epochs": 1, "imgsz": 256, "batch": 1}},
}


def get_all_engines() -> dict:
    """内置 + 插件引擎合并。"""
    engines = {k: dict(v) for k, v in BUILTIN_ENGINES.items()}
    if PLUGINS_DIR.is_dir():
        for spec_file in sorted(PLUGINS_DIR.glob("*/engine.json")):
            try:
                spec = json.loads(spec_file.read_text(encoding="utf-8"))
                if spec.get("id") and spec.get("module"):
                    engines[spec["id"]] = {
                        "module": spec["module"],
                        "task_type": spec.get("task_type", "detect"),
                        "label": spec.get("label", spec["id"]),
                        "defaults": spec.get("defaults", {}),
                    }
            except Exception:
                continue
    return engines


def check_engine(engine: str, task_type: str) -> bool:
    """校验引擎存在且与任务类型匹配。"""
    spec = get_all_engines().get(engine)
    return spec is not None and spec["task_type"] == task_type


def engines_info() -> list[dict]:
    """前端引擎表单配置（不含 module 内部字段）。"""
    return [{"id": e, "label": spec.get("label", e), "task_type": spec["task_type"],
             "defaults": spec.get("defaults", {})}
            for e, spec in sorted(get_all_engines().items())]
