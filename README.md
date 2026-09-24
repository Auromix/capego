# CapEgo

**Open-source egocentric capture and dataset toolkit.**

**开源第一视角采集与数据集工具链。**

> **Status: software prototype / 软件原型。** Continuous capture, durable PC storage, explicit processing, review, dataset snapshots and export run without physical hardware. Synthetic ego data has passed the unmodified EgoWAM Human loader and a reduced HPT world/action training smoke test on macOS CPU. Physical sensors, metric hand reconstruction, released model recipes and NVIDIA GPU operation remain separate validation items.

[观看软件验证演示 / Video demo](design/validation/video-demo.md) · [云端 Codex 接续 / Cloud handoff](design/validation/cloud-handoff.md)

## Run the prototype / 运行原型

Requires Python 3.11+. Run in two terminals:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,export]'
capego serve --root runtime/pc
# Another terminal, using the same virtual environment:
capego simulate --seconds 5
```

The receiver saves packets while capture is running. `capego resume runtime/device/<id>.sqlite3` drains an interrupted outbox. `capego verify <id>` checks PC completeness. `pytest -q` runs fault/recovery tests. See [the implemented protocol](design/system/protocol-v1.md). Runtime data is excluded from Git.

Open **http://localhost:8765** for the offline workbench. Select completed recordings, explicitly start processing, review annotations, save a named dataset and export. `synthetic` processing is a test fixture restricted to synthetic recordings; `quality` performs basic data checks; `local_vlm` requires a separately provisioned local model. Missing geometry is never filled by human approval.

```bash
# One-command HTTP pipeline test (starts and stops its own receiver)
pip install -e '.[dev,export]'
python scripts/demo_pipeline.py --root runtime/demo --egowam

# Independent processing; receiver need not be running
capego process RECORDING_ID --backend synthetic
capego dataset 'Tabletop v1' PROCESSING_ID:task-1
capego export DATASET_ID --format egowam
```

For target-loader and actual loss/backprop validation:

```bash
pip install -e '.[training]' -r requirements-upstream-smoke.txt
git clone https://github.com/GaTech-RL2/EgoWAM.git runtime/EgoWAM
git -C runtime/EgoWAM checkout c87617fe37a6ed6a951e6b176ad552200c425c93
python scripts/validate_egowam.py --upstream runtime/EgoWAM \
  --demo-report runtime/demo/demo-report.json --output runtime/validation/egowam.json
```

This uses EgoWAM's actual Human transforms and HPTModel joint world/action loss with a small configuration and pooled RGB features, without robot data or downloaded pretrained weights. It verifies data use, **not** released-model performance. See [workbench/processing boundaries](design/system/workbench-v1.md).

Local Qwen2.5-VL-3B inference has also run on macOS MPS with synthetic frames. Its constrained semantic proposals require human review; real object tracking and metric geometry estimation are still pending. [Validation evidence](design/validation/2026-09-24-software.md) · [Ubuntu/GPU/model setup](design/validation/ubuntu-runbook.md).

LAN deployment: set the same `CAPEGO_TOKEN` environment variable on receiver and capture process, then run `capego serve --host 0.0.0.0 --allowed-host PC_LAN_IP` and `capego simulate --url http://PC_LAN_IP:8765`. Use only a trusted LAN or a TLS reverse proxy; do not commit tokens. `capego doctor` reports environment readiness without printing credentials.

CapEgo is being designed for open-source developers and researchers, starting with a reproducible reference setup for one person performing tabletop hand operations. During recording, the capture device continuously transfers data to another PC running Ubuntu 24.04 on the same LAN, where it is saved to disk. Users explicitly start batch post-processing; automatic annotation, human review, and versioned dataset production then take place locally. Exported datasets must be validated against named open-source WAM training repositories and versions before compatibility is claimed.

项目面向开源开发者和研究者，首版提供个人或单个实验台能够完整复现的方案，从桌面物体操作开始，并保留更换采集设备、处理工具和导出方式的扩展空间。以下产品行为已确认，具体实现和量化验收条件仍需设计。

| 产品范围 | 期望结果 |
| --- | --- |
| 第一视角采集 | 头戴或胸戴，按按钮开始和结束；一次录制一个文件夹，分块存储、统一读取 |
| 连续传输与保存 | 边采集边持续传输到局域网 Ubuntu 24.04 PC 落盘，设备临时缓存随 PC 可靠保存确认释放 |
| 本地后处理与自动标注 | 用户选择已结束且完整落盘的采集，启动任务、双手运动、操作语义和质量处理 |
| 人工检查 | 优先检查问题片段、抽查其余结果，少量纠正和补充 |
| 数据治理与数据集生产 | 跨记录、跨处理批次筛选组合，保存命名数据集版本，重复导出相同内容 |
| WAM 训练接入 | 验证 ego 数据被目标工程读取并实际参与最小训练；当前不规划机器人数据或要求模型效果复现 |
| 操作与运行 | 可视化工作台为主、命令行为进阶入口；首次准备可联网，准备后全流程无互联网依赖 |

首版由同一台 Ubuntu 24.04 PC 承担接收存储、后处理和工作台，完整后处理以本地 GPU 为参考配置。开始录制前须确认 PC 已连接且能够接收保存。采集接收与后处理独立运行；后处理由用户主动发起，收到新数据不会自动启动。

录制期间边采边传，PC 持续落盘；设备缓存只暂存尚未获得 PC 可靠保存确认的数据，并随确认持续释放。录制途中局域网中断时保留待确认数据，恢复后自动补传。缓存耗尽属于异常，直接结束本次录制、不自动续录，保留已有数据并继续完成传输。

结构化双手动作采用显式有效性与来源标记。当前 EgoWAM 适配已通过模拟数据的缩小配置训练验证；真实三维手部结果和目标发布版训练配置仍待验证。

## Start here / 从这里开始

- [设计入口](design/README.md)
- [已确认的产品范围](design/product/scope.md)
- [完整使用流程](design/product/workflow.md)
- [总体架构与采集保存](design/system/overview.md)
- [后处理、检查与数据集版本](design/data/processing.md)
- [客户提供的候选规格](design/product/customer-inputs.md)
- [数据处理与数据集生产](design/data/README.md)
- [WAM 训练接入要求](design/data/training-integration.md)
- [接下来的设计讨论](design/discussion.md)
- [项目工作约定](AGENTS.md)

## Design approach / 设计方式

先讨论使用者、任务、交付结果和产品边界，再确定软硬件架构、接口、选型和验证方法。`design/` 内的 Markdown 是设计来源；已确认范围、候选方案、实现、测试和验收分别表述。

参考部署和主要数据行为已确认。HTTP/SQLite/JSON 原型协议、HDF5 导出和具名 EgoWAM 适配已实现；相机、安装、采集计算平台、硬同步、生产视频编码、真实几何模型和 GPU 配置仍待验证。客户提供的性能指标是需求输入，不是已实现或已承诺的能力。

## Open-source scope and licensing / 开源范围与许可

开源方向已确定。软件、硬件设计、文档与示例数据的具体许可证尚待讨论，当前尚未配置 LICENSE；公开可见不等于已授予开源许可。

仓库用于设计及后续可公开的工程材料。真实采集数据、客户原始资料、个人信息、凭据和本地产生的数据集不应直接提交到仓库。后续公开示例数据时，应单独说明来源和许可。
