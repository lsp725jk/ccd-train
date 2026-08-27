# 引擎开发指南（类式架构）

## 架构

```
app/engines/
├── base.py        引擎基类 EngineBase（状态/异常/收尾模板）+ sync_ultralytics_curve
├── registry.py    引擎注册表（内置声明 + plugins/engines/*/engine.json 自动发现）
├── data_utils.py  数据公共工具（数据集/图像/标注/类别映射/管线查询）
└── yolo_detect.py 引擎示例（YOLO11 检测）
```

## 新引擎接入（三步）

### 1. 写引擎类

```python
"""我的引擎。"""
from app.engines.base import EngineBase, run_engine
from app.engines.data_utils import load_ds, load_images, load_categories

class MyEngine(EngineBase):
    task_type = "detect"   # detect/segment/classify/us_classify/us_segment

    def run(self):
        cfg = self.cfg
        # 数据准备（从数据库读数据集/图像/标注）
        # 训练（self.set_progress(epoch/total) 更新进度）
        # 评估（写 metrics.json 到 self.run_dir）
        # 收尾：self.weights_path = self.save_weights(best_pt)
        #       self.arch = cfg["engine"]

if __name__ == "__main__":
    run_engine(MyEngine)
```

### 2. 注册

方式 A（内置，改一处）：`app/engines/registry.py` 的 `BUILTIN_ENGINES` 加一行：
```python
"my_engine": {"module": "app.engines.my_engine", "task_type": "detect",
              "label": "My Engine", "defaults": {"epochs": 100, "imgsz": 640, "batch": 16}},
```

方式 B（插件，零代码）：创建 `backend/plugins/engines/my_engine/engine.json`：
```json
{"id": "my_engine", "module": "my_package.my_engine", "task_type": "detect",
 "label": "My Engine", "defaults": {"epochs": 100, "imgsz": 640, "batch": 16}}
```

### 3. 前端零改动

训练表单的引擎下拉、默认参数、任务类型联动全部由 `GET /api/engines` 动态渲染。

## 数据契约（引擎输出约定）

每个训练任务产物在 `data/runs/{task_id}/`：
- `results.csv`   曲线数据（首行表头，EngineBase.write_curve 或 sync_ultralytics_curve）
- `metrics.json`  评估指标
- `weights/best.pt`  权重（self.save_weights）
- `viz/`          评估可视化（PR/混淆矩阵/预测画廊）

## 常用工具

| 工具 | 用途 |
|---|---|
| `EngineBase.set_progress(p)` | 更新任务进度（0-1） |
| `EngineBase.save_weights(src)` | 拷贝权重到约定位置并返回路径 |
| `EngineBase.write_curve(rows, cols)` | 写曲线 CSV |
| `EngineBase.log(msg)` | 输出到训练日志 |
| `get_db()` | SQLite 连接（row_factory=Row） |
| `load_ds/load_images/load_categories` | 数据查询 |
| `cat_index/cat_index_1` | 类别 id → 顺序编号（0 起/1 起） |
| `load_annotations(conn, ds_id, types)` | 标注按图分组 |
| `read_image(ds, im)` | 读取图像 BGR |
| `get_pipeline_ops(conn, pipeline_id)` | 预处理管线算子 |
| `sync_ultralytics_curve(cfg, src, dst, col_map, cols, stop_evt)` | Ultralytics 曲线轮询同步 |

## 进程管理

- 训练队列（`app/services/train_queue.py`）以 `sys.executable -m <module> --config <cfg.json>` 启动引擎
- 必须用 `sys.executable`（Windows PATH 里的 python 会解析到 uv shim）
- 服务重启后 `_recover()` 自动恢复队列（queued 重入队，running 标记失败）
