# CapEgo

**Open-source egocentric capture and dataset toolkit.**

**开源第一视角采集与数据集工具链。**

> **Status: design stage / 设计阶段。** This repository currently contains product scope and discussion inputs. It does not yet provide working hardware, recording software, annotation tools, or verified training integrations.

CapEgo is being designed for open-source developers and researchers, starting with a reproducible reference setup for one person performing tabletop hand operations. During recording, the capture device continuously transfers data to another PC running Ubuntu 24.04 on the same LAN, where it is saved to disk. Users explicitly start batch post-processing; automatic annotation, human review, and versioned dataset production then take place locally. Exported datasets must be validated against named open-source WAM training repositories and versions before compatibility is claimed.

项目面向开源开发者和研究者，首版提供个人或单个实验台能够完整复现的方案，从桌面物体操作开始，并保留更换采集设备、处理工具和导出方式的扩展空间。以下产品行为已确认，具体实现和量化验收条件仍需设计。

| 产品范围 | 期望结果 |
| --- | --- |
| 第一视角采集 | 以头戴或胸戴设备记录自然双手操作；按按钮开始、暂停，任务和片段由后处理识别 |
| 连续传输与保存 | 采集期间持续向同一局域网的另一台 Ubuntu 24.04 PC 传输，并在该 PC 落盘 |
| 本地后处理与自动标注 | 用户选择一批记录并主动启动完整流程，生成结构化双手动作和相关标注 |
| 人工检查 | 优先检查问题片段、抽查其余结果，少量纠正和补充 |
| 数据治理与数据集生产 | 跨记录、跨处理批次筛选组合，保存命名数据集版本，重复导出相同内容 |
| WAM 训练接入 | 导出结果能够实际接入典型开源 WAM 的训练流程；目标仓库和版本待选择验证 |
| 操作与运行 | 可视化工作台为主、命令行为进阶入口；首次准备可联网，准备后全流程无互联网依赖 |

“本地”包括局域网中的接收 PC 和处理算力。采集过程中需要局域网连接，数据传输不等待暂停。后处理由用户主动发起，收到新数据不会自动启动后处理。采集端缓存及后处理是否复用接收 PC 尚待系统设计。

结构化双手动作的数据含义、有效性和训练映射都需要明确。具体文件格式和适配器将按目标训练入口定义；当前尚未完成训练兼容性验证。

## Start here / 从这里开始

- [设计入口](design/README.md)
- [已确认的产品范围](design/product/scope.md)
- [完整使用流程](design/product/workflow.md)
- [客户提供的候选规格](design/product/customer-inputs.md)
- [数据处理与数据集生产](design/data/README.md)
- [WAM 训练接入要求](design/data/training-integration.md)
- [接下来的设计讨论](design/discussion.md)
- [项目工作约定](AGENTS.md)

## Design approach / 设计方式

先讨论使用者、任务、交付结果和产品边界，再确定软硬件架构、接口、选型和验证方法。`design/` 内的 Markdown 是设计来源；已确认范围、候选方案、实现、测试和验收分别表述。

接收并落盘的操作系统已确定为 Ubuntu 24.04。相机组合、安装细节、采集端计算平台、同步机制、传输协议、存储格式、标注算法、后处理部署和目标训练版本仍待设计。客户提供的性能指标是需求输入，不是已实现或已承诺的能力。

## Open-source scope and licensing / 开源范围与许可

开源方向已确定。软件、硬件设计、文档与示例数据的具体许可证尚待讨论，当前尚未配置 LICENSE；公开可见不等于已授予开源许可。

仓库用于设计及后续可公开的工程材料。真实采集数据、客户原始资料、个人信息、凭据和本地产生的数据集不应直接提交到仓库。后续公开示例数据时，应单独说明来源和许可。
