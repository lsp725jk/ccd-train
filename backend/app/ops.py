"""图像预处理与增强算子库。

设计要点：
- 每个算子注册时自带参数 schema（label/type/min/max/step/default），
  前端据此自动生成参数表单，后端据此校验并执行。新增算子不改前端。
- 预处理：确定性变换，OpenCV 实现，输入输出均为 3 通道 BGR。
- 增强：随机性变换，albumentations 实现，预览时固定 seed 可复现。
"""
import base64
import random

import cv2
import numpy as np

# ---------------- 预处理算子实现 ----------------

def _gray(img, **_):
    return cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)


def _gaussian_blur(img, ksize=5, sigma=0, **_):
    return cv2.GaussianBlur(img, (int(ksize), int(ksize)), float(sigma))


def _median_blur(img, ksize=5, **_):
    return cv2.medianBlur(img, int(ksize))


def _bilateral(img, d=9, sigma_color=75, sigma_space=75, **_):
    return cv2.bilateralFilter(img, int(d), float(sigma_color), float(sigma_space))


def _equalize_hist(img, **_):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.equalizeHist(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _clahe(img, clip_limit=2.0, grid=8, **_):
    clahe = cv2.createCLAHE(clipLimit=float(clip_limit), tileGridSize=(int(grid), int(grid)))
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = clahe.apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _dilate(img, ksize=3, iterations=1, **_):
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (int(ksize), int(ksize)))
    return cv2.dilate(img, k, iterations=int(iterations))


def _erode(img, ksize=3, iterations=1, **_):
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (int(ksize), int(ksize)))
    return cv2.erode(img, k, iterations=int(iterations))


def _sharpen(img, amount=1.0, **_):
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharp = cv2.filter2D(img, -1, kernel)
    return cv2.addWeighted(img, 1.0, sharp, float(amount), 0)


def _threshold(img, thresh=128, maxval=255, invert=False, **_):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    t = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    _, out = cv2.threshold(g, int(thresh), int(maxval), t)
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def _brightness(img, delta=0, **_):
    return cv2.convertScaleAbs(img, alpha=1.0, beta=float(delta))


def _contrast(img, alpha=1.0, **_):
    return cv2.convertScaleAbs(img, alpha=float(alpha), beta=0)


def _resize(img, width=640, height=640, **_):
    return cv2.resize(img, (int(width), int(height)), interpolation=cv2.INTER_LINEAR)


def _canny(img, low=50, high=150, **_):
    edges = cv2.Canny(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), int(low), int(high))
    return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)


def _morph_open(img, ksize=3, iterations=1, **_):
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (int(ksize), int(ksize)))
    return cv2.morphologyEx(img, cv2.MORPH_OPEN, k, iterations=int(iterations))


def _morph_close(img, ksize=3, iterations=1, **_):
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (int(ksize), int(ksize)))
    return cv2.morphologyEx(img, cv2.MORPH_CLOSE, k, iterations=int(iterations))


def _adaptive_threshold(img, block=15, C=5, invert=False, **_):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    t = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    block = int(block) if int(block) % 2 == 1 else int(block) + 1
    out = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, t, block, int(C))
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def _gamma(img, gamma=1.5, **_):
    lut = np.array([((i / 255.0) ** float(gamma)) * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(img, lut)


def _normalize(img, **_):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    out = cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX)
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def _invert(img, **_):
    return 255 - img


def _unsharp(img, amount=1.0, sigma=1.5, **_):
    blur = cv2.GaussianBlur(img, (0, 0), float(sigma))
    return cv2.addWeighted(img, 1 + float(amount), blur, -float(amount), 0)


def _white_balance(img, **_):
    result = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    avg_a = float(np.mean(result[:, :, 1]))
    avg_b = float(np.mean(result[:, :, 2]))
    result[:, :, 1] = result[:, :, 1] - ((avg_a - 128) * (result[:, :, 0] / 255.0) * 1.1)
    result[:, :, 2] = result[:, :, 2] - ((avg_b - 128) * (result[:, :, 0] / 255.0) * 1.1)
    return cv2.cvtColor(result, cv2.COLOR_LAB2BGR)


# ---------------- 注册表（预处理） ----------------

def _int_spec(label, default, lo, hi, step=1):
    return {"name": None, "label": label, "type": "int", "min": lo, "max": hi, "step": step, "default": default}


def _float_spec(label, default, lo, hi, step=0.1):
    return {"name": None, "label": label, "type": "float", "min": lo, "max": hi, "step": step, "default": default}


def _named(name, label, func, params):
    return {"name": name, "label": label, "func": func, "params": params}


OP_REGISTRY = {
    "gray": _named("gray", "灰度化", _gray, []),
    "gaussian_blur": _named("gaussian_blur", "高斯模糊", _gaussian_blur, [
        {**_int_spec("核大小", 5, 1, 31, 2), "name": "ksize"},
        {**_float_spec("标准差", 0, 0, 10, 0.1), "name": "sigma"},
    ]),
    "median_blur": _named("median_blur", "中值模糊", _median_blur, [
        {**_int_spec("核大小", 5, 1, 31, 2), "name": "ksize"},
    ]),
    "bilateral": _named("bilateral", "双边滤波", _bilateral, [
        {**_int_spec("直径 d", 9, 1, 50), "name": "d"},
        {**_int_spec("颜色 sigma", 75, 1, 200), "name": "sigma_color"},
        {**_int_spec("空间 sigma", 75, 1, 200), "name": "sigma_space"},
    ]),
    "equalize_hist": _named("equalize_hist", "直方图均衡", _equalize_hist, []),
    "clahe": _named("clahe", "CLAHE 增强", _clahe, [
        {**_float_spec("对比度上限", 2.0, 0.5, 8.0, 0.5), "name": "clip_limit"},
        {**_int_spec("网格", 8, 2, 32), "name": "grid"},
    ]),
    "dilate": _named("dilate", "膨胀", _dilate, [
        {**_int_spec("核大小", 3, 1, 31, 2), "name": "ksize"},
        {**_int_spec("迭代次数", 1, 1, 10), "name": "iterations"},
    ]),
    "erode": _named("erode", "收缩", _erode, [
        {**_int_spec("核大小", 3, 1, 31, 2), "name": "ksize"},
        {**_int_spec("迭代次数", 1, 1, 10), "name": "iterations"},
    ]),
    "sharpen": _named("sharpen", "锐化", _sharpen, [
        {**_float_spec("强度", 1.0, 0, 3.0, 0.1), "name": "amount"},
    ]),
    "threshold": _named("threshold", "二值化", _threshold, [
        {**_int_spec("阈值", 128, 0, 255), "name": "thresh"},
        {**_int_spec("最大值", 255, 1, 255), "name": "maxval"},
        {"name": "invert", "label": "反相", "type": "bool", "default": False},
    ]),
    "brightness": _named("brightness", "亮度调整", _brightness, [
        {**_int_spec("增量", 0, -150, 150), "name": "delta"},
    ]),
    "contrast": _named("contrast", "对比度调整", _contrast, [
        {**_float_spec("系数", 1.0, 0.1, 3.0, 0.05), "name": "alpha"},
    ]),
    "resize": _named("resize", "尺寸归一化", _resize, [
        {**_int_spec("宽度", 640, 64, 4096, 32), "name": "width"},
        {**_int_spec("高度", 640, 64, 4096, 32), "name": "height"},
    ]),
    "canny": _named("canny", "边缘检测", _canny, [
        {**_int_spec("低阈值", 50, 0, 255), "name": "low"},
        {**_int_spec("高阈值", 150, 0, 255), "name": "high"},
    ]),
    "morph_open": _named("morph_open", "开运算（去小噪点）", _morph_open, [
        {**_int_spec("核大小", 3, 1, 31, 2), "name": "ksize"},
        {**_int_spec("迭代次数", 1, 1, 10), "name": "iterations"},
    ]),
    "morph_close": _named("morph_close", "闭运算（填小洞）", _morph_close, [
        {**_int_spec("核大小", 3, 1, 31, 2), "name": "ksize"},
        {**_int_spec("迭代次数", 1, 1, 10), "name": "iterations"},
    ]),
    "adaptive_threshold": _named("adaptive_threshold", "自适应二值化", _adaptive_threshold, [
        {**_int_spec("邻域块", 15, 3, 99, 2), "name": "block"},
        {**_int_spec("常数 C", 5, -20, 20), "name": "C"},
        {"name": "invert", "label": "反相", "type": "bool", "default": False},
    ]),
    "gamma": _named("gamma", "伽马校正", _gamma, [
        {**_float_spec("伽马值", 1.5, 0.1, 5.0, 0.1), "name": "gamma"},
    ]),
    "normalize": _named("normalize", "灰度拉伸", _normalize, []),
    "invert": _named("invert", "反相", _invert, []),
    "unsharp": _named("unsharp", "USM 锐化", _unsharp, [
        {**_float_spec("强度", 1.0, 0.1, 3.0, 0.1), "name": "amount"},
        {**_float_spec("模糊半径", 1.5, 0.1, 10.0, 0.1), "name": "sigma"},
    ]),
    "white_balance": _named("white_balance", "白平衡（灰世界）", _white_balance, []),
}

# ---------------- 增强算子（albumentations） ----------------

import albumentations as A  # noqa: E402


def _aug(name, label, builder, params):
    return {"name": name, "label": label, "builder": builder, "params": params}


AUG_REGISTRY = {
    "hflip": _aug("hflip", "水平翻转",
                  lambda p=1.0: A.HorizontalFlip(p=float(p)),
                  [{**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"}]),
    "vflip": _aug("vflip", "垂直翻转",
                  lambda p=1.0: A.VerticalFlip(p=float(p)),
                  [{**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"}]),
    "rotate90": _aug("rotate90", "90° 随机旋转",
                     lambda p=1.0: A.RandomRotate90(p=float(p)),
                     [{**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"}]),
    "rotate": _aug("rotate", "任意角度旋转",
                   lambda limit=15, p=1.0: A.Rotate(limit=(float(-limit), float(limit)), border_mode=cv2.BORDER_CONSTANT, p=float(p)),
                   [
                       {**_int_spec("角度上限", 15, 1, 180), "name": "limit"},
                       {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                   ]),
    "scale": _aug("scale", "随机缩放",
                  lambda limit=0.1, p=1.0: A.Affine(scale=(1.0 - float(limit), 1.0 + float(limit)), p=float(p)),
                  [
                      {**_float_spec("缩放幅度", 0.1, 0.0, 0.5, 0.05), "name": "limit"},
                      {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                  ]),
    "brightness": _aug("brightness", "亮度扰动",
                       lambda limit=0.2, p=1.0: A.RandomBrightnessContrast(
                           brightness_limit=(float(-limit), float(limit)), contrast_limit=0, p=float(p)),
                       [
                           {**_float_spec("幅度", 0.2, 0.0, 0.8, 0.05), "name": "limit"},
                           {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                       ]),
    "contrast": _aug("contrast", "对比度扰动",
                     lambda limit=0.2, p=1.0: A.RandomBrightnessContrast(
                         brightness_limit=0, contrast_limit=(float(-limit), float(limit)), p=float(p)),
                     [
                         {**_float_spec("幅度", 0.2, 0.0, 0.8, 0.05), "name": "limit"},
                         {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                     ]),
    "hue_sat": _aug("hue_sat", "色相饱和度扰动",
                    lambda hue=15, sat=20, p=1.0: A.HueSaturationValue(
                        hue_shift_limit=int(hue), sat_shift_limit=int(sat), p=float(p)),
                    [
                        {**_int_spec("色相幅度", 15, 0, 90), "name": "hue"},
                        {**_int_spec("饱和度幅度", 20, 0, 90), "name": "sat"},
                        {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                    ]),
    "gauss_noise": _aug("gauss_noise", "高斯噪声",
                        lambda var=40.0, p=1.0: A.GaussNoise(var_limit=(0.0, float(var)), p=float(p)),
                        [
                            {**_float_spec("方差上限", 40.0, 5, 255, 5), "name": "var"},
                            {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                        ]),
    "salt_pepper": _aug("salt_pepper", "椒盐噪声",
                        lambda amount=0.03, p=1.0: A.SaltAndPepper(amount=float(amount), p=float(p)),
                        [
                            {**_float_spec("比例", 0.03, 0.0, 0.2, 0.01), "name": "amount"},
                            {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                        ]),
    "blur": _aug("blur", "模糊",
                 lambda limit=3, p=1.0: A.Blur(blur_limit=(3, int(limit) * 2 + 1), p=float(p)),
                 [
                     {**_int_spec("模糊强度", 3, 1, 7), "name": "limit"},
                     {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                 ]),
    "cutout": _aug("cutout", "随机遮挡 Cutout",
                    lambda holes=8, size=32, p=1.0: A.CoarseDropout(
                        max_holes=int(holes), max_height=int(size), max_width=int(size),
                        fill_value=128, p=float(p)),
                    [
                        {**_int_spec("空洞数", 8, 1, 20), "name": "holes"},
                        {**_int_spec("空洞尺寸", 32, 8, 128, 8), "name": "size"},
                        {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                    ]),
    "elastic": _aug("elastic", "弹性形变",
                     lambda alpha=1.0, sigma=50, p=1.0: A.ElasticTransform(
                         alpha=float(alpha), sigma=float(sigma), p=float(p)),
                     [
                         {**_float_spec("强度 alpha", 1.0, 0.1, 5.0, 0.1), "name": "alpha"},
                         {**_int_spec("平滑 sigma", 50, 10, 100), "name": "sigma"},
                         {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                     ]),
    "grid_distortion": _aug("grid_distortion", "网格畸变",
                             lambda limit=0.3, p=1.0: A.GridDistortion(
                                 num_steps=5, distort_limit=float(limit), p=float(p)),
                             [
                                 {**_float_spec("畸变幅度", 0.3, 0.05, 0.5, 0.05), "name": "limit"},
                                 {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                             ]),
    "perspective": _aug("perspective", "透视扰动",
                         lambda scale=0.08, p=1.0: A.Perspective(scale=(0.03, float(scale)), p=float(p)),
                         [
                             {**_float_spec("幅度", 0.08, 0.02, 0.2, 0.01), "name": "scale"},
                             {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                         ]),
    "downscale": _aug("downscale", "降采样（低分辨率）",
                       lambda min_s=0.5, p=1.0: A.Downscale(
                           scale_range=(float(min_s), 0.9), p=float(p)),
                       [
                           {**_float_spec("最低比例", 0.5, 0.2, 0.9, 0.05), "name": "min_s"},
                           {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                       ]),
    "iso_noise": _aug("iso_noise", "ISO 噪声",
                       lambda intensity=0.3, p=1.0: A.ISONoise(
                           color_shift=(0.01, 0.05), intensity=(0.1, float(intensity)), p=float(p)),
                       [
                           {**_float_spec("强度", 0.3, 0.05, 0.5, 0.05), "name": "intensity"},
                           {**_float_spec("概率", 1.0, 0, 1, 0.05), "name": "p"},
                       ]),
}

# ---------------- 执行入口 ----------------

def apply_preprocess(img: np.ndarray, ops: list[dict]) -> np.ndarray:
    """按顺序应用预处理算子（确定性）。enabled=false 的算子跳过。"""
    for op in ops:
        if op.get("enabled") is False:
            continue
        spec = OP_REGISTRY.get(op.get("name", ""))
        if not spec:
            raise ValueError(f"未知预处理算子: {op.get('name')}")
        img = spec["func"](img, **(op.get("params") or {}))
    return img


def build_augmentation(augs: list[dict], seed: int | None = None):
    """构建增强变换组合。seed 固定时可复现，用于预览。enabled=false 的算子跳过。"""
    transforms = []
    for a in augs:
        if a.get("enabled") is False:
            continue
        spec = AUG_REGISTRY.get(a.get("name", ""))
        if not spec:
            raise ValueError(f"未知增强算子: {a.get('name')}")
        transforms.append(spec["builder"](**(a.get("params") or {})))
    if not transforms:
        raise ValueError("增强管线为空（所有算子均被禁用）")
    try:
        return A.Compose(transforms, seed=seed)
    except TypeError:
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        return A.Compose(transforms)


def apply_augmentation(img: np.ndarray, augs: list[dict], seed: int | None = None) -> np.ndarray:
    transform = build_augmentation(augs, seed)
    return transform(image=img)["image"]


def encode_preview(img: np.ndarray, max_side: int = 1280) -> str:
    """缩放到最长边不超过 max_side，编码为 base64 data URL。"""
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("图像编码失败")
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")
