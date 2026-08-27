"""内置场景知识库：检测物品 → 缺陷类型 → 推荐方案。

结构约定：
- SCENES: 一级分类（按检测物品），每个含 items（具体物品）
- item.defects: 缺陷类型列表，每项 tags 用于选型规则：
    "微小"  目标小（<32px），需要高分辨率输入
    "纹理"  纹理/线状缺陷，适合无监督异常检测兜底
    "区域"  大面积区域缺陷，适合分割或检测
- item.recommend: 基准方案 {task_types, engines, defaults, pre_ops, note}
    engines: [{engine, task_type, role}]  role: 主检测/无监督兜底/分割精修
    pre_ops: 建议预处理算子 [{name, params, enabled}]

用户自定义方案存 data/custom_scenes.json（见 routers/scenes.py）。
"""
from copy import deepcopy

SCENES = [
    {
        "id": "metal",
        "name": "金属表面",
        "items": [
            {
                "id": "steel_sheet",
                "name": "钢板 / 金属件表面",
                "defects": [
                    {"name": "裂纹", "tags": ["纹理", "线状"]},
                    {"name": "划痕", "tags": ["纹理", "线状"]},
                    {"name": "凹坑 / 点蚀", "tags": ["点状"]},
                    {"name": "麻点", "tags": ["点状", "微小"]},
                    {"name": "杂质夹杂", "tags": ["点状"]},
                    {"name": "氧化皮 / 斑痕", "tags": ["区域"]},
                    {"name": "毛刺", "tags": ["点状", "线状"]},
                ],
                "recommend": {
                    "task_types": ["detect", "us_segment"],
                    "engines": [
                        {"engine": "yolo11n", "task_type": "detect", "role": "主检测"},
                        {"engine": "patchcore", "task_type": "us_segment", "role": "无监督兜底"},
                    ],
                    "defaults": {"epochs": 100, "imgsz": 640, "batch": 16},
                    "pre_ops": [
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": True},
                        {"name": "sharpen", "params": {"amount": 1.0}, "enabled": False},
                    ],
                    "note": "金属表面纹理反光强，低对比度缺陷建议开启预处理增强（CLAHE）。",
                },
            },
            {
                "id": "solder_joint",
                "name": "焊点 / 焊接质量",
                "defects": [
                    {"name": "虚焊", "tags": ["点状", "微小"]},
                    {"name": "冷焊", "tags": ["点状"]},
                    {"name": "桥连", "tags": ["线状"]},
                    {"name": "焊渣飞溅", "tags": ["点状", "微小"]},
                    {"name": "漏焊", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect"],
                    "engines": [
                        {"engine": "yolo11m", "task_type": "detect", "role": "主检测"},
                    ],
                    "defaults": {"epochs": 120, "imgsz": 1280, "batch": 4},
                    "pre_ops": [
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": True},
                        {"name": "median_blur", "params": {"ksize": 3}, "enabled": False},
                    ],
                    "note": "焊点缺陷微小，需高分辨率输入；有正常焊点图时建议加 PatchCore 兜底。",
                },
            },
        ],
    },
    {
        "id": "pcb",
        "name": "PCB / 电子",
        "items": [
            {
                "id": "pcb_bare",
                "name": "PCB 裸板",
                "defects": [
                    {"name": "断线", "tags": ["线状", "微小"]},
                    {"name": "短路 / 铜桥", "tags": ["线状", "微小"]},
                    {"name": "缺口", "tags": ["区域", "微小"]},
                    {"name": "毛刺", "tags": ["点状", "微小"]},
                    {"name": "污染", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect"],
                    "engines": [
                        {"engine": "yolo11m", "task_type": "detect", "role": "主检测"},
                    ],
                    "defaults": {"epochs": 120, "imgsz": 1280, "batch": 4},
                    "pre_ops": [
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": True},
                        {"name": "sharpen", "params": {"amount": 1.0}, "enabled": True},
                    ],
                    "note": "PCB 缺陷普遍微小，优先高分辨率输入 + 中等模型。",
                },
            },
            {
                "id": "pcba",
                "name": "PCBA 贴片 / 焊后检测",
                "defects": [
                    {"name": "缺件", "tags": ["区域"]},
                    {"name": "极性翻转", "tags": ["区域"]},
                    {"name": "偏移 / 错位", "tags": ["区域"]},
                    {"name": "墓碑现象", "tags": ["区域"]},
                    {"name": "焊桥", "tags": ["线状"]},
                    {"name": "冷焊 / 虚焊", "tags": ["点状", "微小"]},
                ],
                "recommend": {
                    "task_types": ["detect", "classify"],
                    "engines": [
                        {"engine": "yolo11n", "task_type": "detect", "role": "主检测"},
                    ],
                    "defaults": {"epochs": 100, "imgsz": 1280, "batch": 4},
                    "pre_ops": [
                        {"name": "normalize", "params": {}, "enabled": False},
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": False},
                    ],
                    "note": "缺件/极性类缺陷定位明确，检测即可；如只需判断有无，可改用分类任务。",
                },
            },
            {
                "id": "fpc",
                "name": "FPC 软板",
                "defects": [
                    {"name": "线路损伤", "tags": ["线状", "微小"]},
                    {"name": "覆盖膜剥离", "tags": ["区域"]},
                    {"name": "焊垫污染", "tags": ["区域"]},
                    {"name": "划痕", "tags": ["纹理", "线状"]},
                ],
                "recommend": {
                    "task_types": ["detect", "us_segment"],
                    "engines": [
                        {"engine": "yolo11n", "task_type": "detect", "role": "主检测"},
                        {"engine": "patchcore", "task_type": "us_segment", "role": "无监督兜底"},
                    ],
                    "defaults": {"epochs": 100, "imgsz": 960, "batch": 8},
                    "pre_ops": [
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": True},
                        {"name": "gaussian_blur", "params": {"ksize": 3, "sigma": 0}, "enabled": False},
                    ],
                    "note": "软板弯曲反光，建议固定治具 + 均匀光源；纹理损伤适合无监督兜底。",
                },
            },
        ],
    },
    {
        "id": "textile",
        "name": "纺织",
        "items": [
            {
                "id": "fabric",
                "name": "织物 / 布料",
                "defects": [
                    {"name": "断纱", "tags": ["线状"]},
                    {"name": "织纹不匀", "tags": ["纹理", "区域"]},
                    {"name": "污渍 / 油污", "tags": ["区域"]},
                    {"name": "破洞", "tags": ["区域"]},
                    {"name": "色差", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect", "us_segment", "segment"],
                    "engines": [
                        {"engine": "yolo11n", "task_type": "detect", "role": "主检测"},
                        {"engine": "patchcore", "task_type": "us_segment", "role": "无监督兜底"},
                        {"engine": "unet_resnet18", "task_type": "segment", "role": "分割精修"},
                    ],
                    "defaults": {"epochs": 100, "imgsz": 640, "batch": 16},
                    "pre_ops": [
                        {"name": "normalize", "params": {}, "enabled": True},
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": False},
                    ],
                    "note": "纹理类缺陷在特征空间区分度高，无监督兜底效果好；破洞等区域缺陷可分割精修。",
                },
            },
        ],
    },
    {
        "id": "glass_ceramic",
        "name": "玻璃 / 陶瓷",
        "items": [
            {
                "id": "glass",
                "name": "玻璃制品",
                "defects": [
                    {"name": "气泡", "tags": ["点状", "微小"]},
                    {"name": "裂纹", "tags": ["纹理", "线状"]},
                    {"name": "划痕", "tags": ["纹理", "线状"]},
                    {"name": "结石", "tags": ["点状"]},
                    {"name": "污渍", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect"],
                    "engines": [
                        {"engine": "yolo11m", "task_type": "detect", "role": "主检测"},
                    ],
                    "defaults": {"epochs": 120, "imgsz": 1280, "batch": 4},
                    "pre_ops": [
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": True},
                        {"name": "gaussian_blur", "params": {"ksize": 3, "sigma": 0}, "enabled": False},
                    ],
                    "note": "透明材质对光照敏感，建议背光或低角度光源；气泡等微小缺陷需高分辨率。",
                },
            },
            {
                "id": "ceramic",
                "name": "陶瓷 / 釉面",
                "defects": [
                    {"name": "釉泡", "tags": ["点状", "微小"]},
                    {"name": "针孔", "tags": ["点状", "微小"]},
                    {"name": "裂纹", "tags": ["纹理", "线状"]},
                    {"name": "色差", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect"],
                    "engines": [
                        {"engine": "yolo11m", "task_type": "detect", "role": "主检测"},
                    ],
                    "defaults": {"epochs": 120, "imgsz": 960, "batch": 8},
                    "pre_ops": [
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": True},
                    ],
                    "note": "釉面反光不均，预处理建议 CLAHE 增强。",
                },
            },
        ],
    },
    {
        "id": "plastic_rubber",
        "name": "塑料 / 橡胶",
        "items": [
            {
                "id": "injection",
                "name": "注塑件 / 橡胶件",
                "defects": [
                    {"name": "毛边 / 飞边", "tags": ["线状"]},
                    {"name": "缺料", "tags": ["区域"]},
                    {"name": "气泡", "tags": ["点状", "微小"]},
                    {"name": "缩水", "tags": ["区域"]},
                    {"name": "划痕", "tags": ["纹理", "线状"]},
                    {"name": "色差", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect", "classify"],
                    "engines": [
                        {"engine": "yolo11n", "task_type": "detect", "role": "主检测"},
                    ],
                    "defaults": {"epochs": 100, "imgsz": 640, "batch": 16},
                    "pre_ops": [
                        {"name": "sharpen", "params": {"amount": 1.0}, "enabled": True},
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": False},
                    ],
                    "note": "注塑件位置固定，可先试分类任务，精度不足再升级检测。",
                },
            },
        ],
    },
    {
        "id": "wood",
        "name": "木材",
        "items": [
            {
                "id": "wood_board",
                "name": "木板 / 人造板",
                "defects": [
                    {"name": "裂纹", "tags": ["纹理", "线状"]},
                    {"name": "节疤", "tags": ["区域"]},
                    {"name": "虫眼", "tags": ["点状", "微小"]},
                    {"name": "污渍", "tags": ["区域"]},
                    {"name": "腐朽", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect", "us_segment", "segment"],
                    "engines": [
                        {"engine": "yolo11n", "task_type": "detect", "role": "主检测"},
                        {"engine": "patchcore", "task_type": "us_segment", "role": "无监督兜底"},
                        {"engine": "unet_resnet18", "task_type": "segment", "role": "分割精修"},
                    ],
                    "defaults": {"epochs": 100, "imgsz": 640, "batch": 16},
                    "pre_ops": [
                        {"name": "normalize", "params": {}, "enabled": True},
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": False},
                    ],
                    "note": "木纹本身是强纹理背景，无监督方法可学习正常木纹；节疤/腐朽等区域缺陷可分割精修。",
                },
            },
        ],
    },
    {
        "id": "solar",
        "name": "光伏",
        "items": [
            {
                "id": "pv_cell",
                "name": "电池片（EL / 外观）",
                "defects": [
                    {"name": "隐裂", "tags": ["纹理", "线状"]},
                    {"name": "碎片", "tags": ["区域"]},
                    {"name": "断栅", "tags": ["线状", "微小"]},
                    {"name": "黑斑", "tags": ["区域"]},
                    {"name": "污染", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect", "us_segment"],
                    "engines": [
                        {"engine": "yolo11m", "task_type": "detect", "role": "主检测"},
                        {"engine": "patchcore", "task_type": "us_segment", "role": "无监督兜底"},
                    ],
                    "defaults": {"epochs": 120, "imgsz": 1280, "batch": 4},
                    "pre_ops": [
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": True},
                        {"name": "normalize", "params": {}, "enabled": False},
                    ],
                    "note": "EL 成像下隐裂/断栅为线状微小缺陷，高分辨率 + 无监督兜底组合收益大。",
                },
            },
        ],
    },
    {
        "id": "connector",
        "name": "连接器 / 线束",
        "items": [
            {
                "id": "connector_terminal",
                "name": "端子 / 连接器",
                "defects": [
                    {"name": "变形", "tags": ["区域"]},
                    {"name": "压接不良", "tags": ["区域"]},
                    {"name": "异物", "tags": ["点状"]},
                    {"name": "氧化", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect", "classify"],
                    "engines": [
                        {"engine": "yolo11n", "task_type": "detect", "role": "主检测"},
                    ],
                    "defaults": {"epochs": 100, "imgsz": 640, "batch": 16},
                    "pre_ops": [
                        {"name": "normalize", "params": {}, "enabled": True},
                    ],
                    "note": "端子位姿固定，分类先试；变形类需区域定位时用检测。",
                },
            },
            {
                "id": "wiring_harness",
                "name": "线束",
                "defects": [
                    {"name": "线序错误", "tags": ["区域"]},
                    {"name": "破损 / 露铜", "tags": ["区域"]},
                    {"name": "端子偏移", "tags": ["区域"]},
                ],
                "recommend": {
                    "task_types": ["detect", "segment"],
                    "engines": [
                        {"engine": "yolo11n", "task_type": "detect", "role": "主检测"},
                        {"engine": "unet_resnet18", "task_type": "segment", "role": "分割精修"},
                    ],
                    "defaults": {"epochs": 100, "imgsz": 640, "batch": 16},
                    "pre_ops": [
                        {"name": "clahe", "params": {"clip_limit": 2.0, "grid": 8}, "enabled": True},
                    ],
                    "note": "破损/露铜等区域缺陷边界不规则，分割可获精确轮廓。",
                },
            },
        ],
    },
]

# 任务类型说明（前端展示用）
TASK_TYPE_LABELS = {
    "detect": "目标检测（框定位）",
    "classify": "图像分类（有无判断）",
    "segment": "像素分割（轮廓）",
    "us_segment": "无监督异常检测（无需缺陷标注）",
}

# 场景推荐增强（按 item_id 索引，与 pre_ops 对称）。
# 参数均取保守值：只模拟产线物理真实变化（光照波动/噪声/摆放公差），
# 不做大角度旋转、强色相偏移等可能引入错误信号的增强。
AUG_PRESETS = {
    "steel_sheet": [
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
        {"name": "gauss_noise", "params": {"var": 15, "p": 0.5}, "enabled": True},
        {"name": "scale", "params": {"limit": 0.03, "p": 0.5}, "enabled": False},
    ],
    "solder_joint": [
        {"name": "brightness", "params": {"limit": 0.08, "p": 0.8}, "enabled": True},
        {"name": "gauss_noise", "params": {"var": 15, "p": 0.5}, "enabled": True},
    ],
    "pcb_bare": [
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
        {"name": "contrast", "params": {"limit": 0.1, "p": 0.5}, "enabled": True},
        {"name": "scale", "params": {"limit": 0.02, "p": 0.3}, "enabled": False},
    ],
    "pcba": [
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
        {"name": "contrast", "params": {"limit": 0.1, "p": 0.5}, "enabled": True},
    ],
    "fpc": [
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
        {"name": "gauss_noise", "params": {"var": 15, "p": 0.5}, "enabled": True},
    ],
    "fabric": [
        {"name": "hflip", "params": {"p": 0.5}, "enabled": True},
        {"name": "scale", "params": {"limit": 0.05, "p": 0.5}, "enabled": True},
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
    ],
    "glass": [
        {"name": "brightness", "params": {"limit": 0.08, "p": 0.8}, "enabled": True},
        {"name": "contrast", "params": {"limit": 0.08, "p": 0.5}, "enabled": True},
        {"name": "gauss_noise", "params": {"var": 15, "p": 0.3}, "enabled": False},
    ],
    "ceramic": [
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
        {"name": "gauss_noise", "params": {"var": 20, "p": 0.5}, "enabled": True},
    ],
    "injection": [
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
        {"name": "contrast", "params": {"limit": 0.1, "p": 0.5}, "enabled": True},
        {"name": "hflip", "params": {"p": 0.5}, "enabled": False},
    ],
    "wood_board": [
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
        {"name": "scale", "params": {"limit": 0.05, "p": 0.5}, "enabled": True},
        {"name": "hflip", "params": {"p": 0.5}, "enabled": True},
    ],
    "pv_cell": [
        {"name": "brightness", "params": {"limit": 0.08, "p": 0.8}, "enabled": True},
        {"name": "contrast", "params": {"limit": 0.08, "p": 0.5}, "enabled": True},
    ],
    "connector_terminal": [
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
        {"name": "scale", "params": {"limit": 0.02, "p": 0.3}, "enabled": False},
    ],
    "wiring_harness": [
        {"name": "hflip", "params": {"p": 0.5}, "enabled": True},
        {"name": "brightness", "params": {"limit": 0.1, "p": 0.8}, "enabled": True},
    ],
}


def build_plan(item: dict, defect_names: list[str]) -> dict:
    """按勾选的缺陷类型生成推荐方案。

    规则（底层依据）：
    1. 基准方案取 item.recommend
    2. 含「微小」缺陷 → 提升输入分辨率（1280），相应降低 batch
    3. 含「纹理」缺陷且基准带 patchcore → 保留无监督兜底并提示
    """
    rec = item["recommend"]
    selected = [d for d in item["defects"] if d["name"] in defect_names]
    tags = set()
    for d in selected:
        tags.update(d.get("tags", []))

    engines = deepcopy(rec["engines"])
    defaults = dict(rec["defaults"])
    notes = []
    if "微小" in tags:
        if defaults.get("imgsz", 640) < 1280:
            defaults["imgsz"] = 1280
            defaults["batch"] = 4
            notes.append("存在微小缺陷，输入分辨率已提升至 1280（batch 相应降低）")
    if "纹理" in tags:
        if any(e["engine"] == "patchcore" for e in engines):
            notes.append("纹理类缺陷在特征空间区分度高，已保留 PatchCore 无监督兜底")
        else:
            notes.append("含纹理类缺陷，如正常样本充足，建议追加 PatchCore 无监督兜底")
    if "区域" in tags and len(tags & {"纹理", "点状"}) == 0:
        notes.append("以区域型缺陷为主，可考虑分割任务（UNet）获得像素级轮廓")
    if not defect_names:
        notes.append("未勾选缺陷类型，方案使用基准配置")

    return {"engines": engines, "defaults": defaults, "notes": notes,
            "pre_ops": rec.get("pre_ops", []), "aug_ops": AUG_PRESETS.get(item["id"], [])}


def scene_tree() -> list[dict]:
    """返回内置场景树（含推荐方案），供前端渲染。"""
    tree = []
    for scene in SCENES:
        items = []
        for item in scene["items"]:
            items.append({
                "id": item["id"],
                "name": item["name"],
                "defects": item["defects"],
                "recommend": item["recommend"],
                "note": item["recommend"]["note"],
            })
        tree.append({"id": scene["id"], "name": scene["name"], "custom": False, "items": items})
    return tree
