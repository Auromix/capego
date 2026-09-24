# 云端 Codex 接续：Ubuntu / NVIDIA 验证

更新：2026-09-24。此文件用于在云电脑内直接运行 Codex 时接续项目，避免依赖远程桌面截图。它不是云 GPU 验证通过声明。

## 可直接粘贴给云端 Codex 的任务

```text
继续 Auromix/capego 的云端验证。先阅读 AGENTS.md、design/implementation.md、
design/validation/2026-09-24-software.md、design/validation/ubuntu-runbook.md 和本文件。
保持已确认的产品边界，不重新设计硬件，也不引入机器人数据。

你现在运行在需要验证的云电脑内部。检查实际操作系统、Python、磁盘、
NVIDIA 驱动、GPU 型号/显存和 PyTorch CUDA；使用项目虚拟环境，勿自动升级系统驱动。
依次运行测试、真实 HTTP 模拟采集到导出、官方 EgoWAM 固定版本的 CPU/CUDA
最小训练，以及本地 Qwen VLM 标注。修复发现的问题，保留失败证据再重试。
只有真实执行且通过才能记录 passed；CPU 通过不能替代 CUDA 通过。

验证 2 秒和 45 秒模拟录制，检查录制时持续落盘、结束后缓存清空、9 个 5 秒块的
统一读取、主动启动后处理、检查修订、不可变快照及 HDF5/EgoWAM 导出。
使用合成几何做格式/训练链路测试时明确标注 synthetic；VLM 不能补造几何。

以 design/validation/ 中的中文报告和脱敏 JSON 记录命令、版本、结果、
耗时、峰值显存和剩余限制。不要提交账号、凭据、主机地址、环境变量全集、
模型权重或 runtime 中的数据集。工作达到可复现状态后提交 GitHub；若云端尚无
GitHub 写权限，保留本地提交并报告，不把登录凭据写入文件或消息。

macOS 端正在制作演示视频；本任务优先交付 GPU 和 VLM 验证证据，避免重复改动视频。
持续工作直到已实现部分验证完成，或者出现确实需要我协助的外部阻塞。
```

## 接续时已知状态

- 首个原型基线提交：`bc17c87660527cef7784e0ce17241dbb4fa7cef3`；接续时以当前 `main` 为准。
- 24 项测试、本地 HTTP 完整链路、官方 EgoWAM 缩小配置 CPU 联合世界/动作训练已通过。
- GitHub Actions 的 Ubuntu/macOS × Python 3.11/3.12 测试和 Ubuntu CPU 训练已通过。
- 本地 Qwen2.5-VL-3B 曾在 Mac MPS 上完成结构化标注，但存在描述误差，全部待人工检查。
- 新增 45 秒、320×240、双 RGB 10 Hz + IMU 50 Hz 模拟录制：3,150 包、9 个 5 秒块，
  持续接收、完整落盘、检查、快照、两种导出和同一导出数据的 CPU 训练再次通过。
- 本轮 45 秒录制的一次 VLM 尝试失败：返回未完成的 JSON（原文停在描述字段），
  被契约校验拒绝。生成配置有 300 秒上限；仅凭截断输出尚不能确定终止原因。
  需要在云 GPU 上复现并记录生成耗时、token 数与终止条件，不将该尝试计为通过。
- 没有实体设备；硬同步、目标视频吞吐、真实物体跟踪、真实三维手部/相机轨迹尚未验证。
- 无影桌面可以由人查看，但 Mac 自动化截图和可访问性接口无法读取其终端。
  尚未取得任何云端命令执行结果，不能根据云电脑规格卡推断 CUDA 可用。

## 固定参考版本与命令

依照 [Ubuntu 复现步骤](ubuntu-runbook.md) 安装依赖并生成 `demo-report.json`。

- EgoWAM：`https://github.com/GaTech-RL2/EgoWAM`，提交
  `c87617fe37a6ed6a951e6b176ad552200c425c93`；验证脚本要求 upstream tracked source 未修改。
- Qwen：`Qwen/Qwen2.5-VL-3B-Instruct`，revision
  `66285546d2b821cf421d4f5eb2576359d3770cd3`；预先下载后离线推理。
- NVIDIA 训练命令在 runbook 的 `validate_egowam.py` 调用中添加 `--device cuda`。
- `capego process ... --wait 600` 的 `--wait` 需要秒数，不能单独写 `--wait`。

训练通过至少要有有限且非零的 loss/gradient，主干、动作头和世界头均发生参数更新。
当前脚本是缩小模型配置的数据可用性 smoke test，不是论文配置复现或效果验收。

## 安装云端 Codex

在云电脑内安装并登录后，从仓库目录启动。官方支持 Linux CLI：
[安装](https://learn.chatgpt.com/docs/codex/cli)、[登录](https://learn.chatgpt.com/docs/auth)。
项目代码和文档通过 GitHub 同步；不要假定 Mac 会话、技能、模型文件、登录或未提交的
本地素材会随安装自动迁移。
