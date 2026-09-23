# CapEgo

**Open-source egocentric capture and dataset toolkit.**

**开源第一视角采集与数据集工具链。**

> **Status: design stage / 设计阶段。** This repository contains product scope and agreed system and data-processing designs. It does not yet provide working hardware, recording software, annotation tools, or verified training integrations.

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

结构化双手动作的数据含义、有效性和训练映射都需要明确。具体文件格式和适配器将按目标训练入口定义；当前尚未完成训练兼容性验证。

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

参考部署和主要数据行为已确认。相机组合、安装细节、采集端计算平台、同步机制、传输协议、存储格式、具体标注模型、GPU 配置和目标训练版本仍待设计。客户提供的性能指标是需求输入，不是已实现或已承诺的能力。

## Open-source scope and licensing / 开源范围与许可

开源方向已确定。软件、硬件设计、文档与示例数据的具体许可证尚待讨论，当前尚未配置 LICENSE；公开可见不等于已授予开源许可。

仓库用于设计及后续可公开的工程材料。真实采集数据、客户原始资料、个人信息、凭据和本地产生的数据集不应直接提交到仓库。后续公开示例数据时，应单独说明来源和许可。
