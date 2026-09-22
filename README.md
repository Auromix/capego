# captureego

**Open-source ego / egocentric data collection, local annotation, and dataset production for robot learning.**

**开源第一视角采集、本地标注与数据集生产项目。**

> **Status: design stage / 设计阶段。** This repository currently contains product scope and discussion inputs. It does not yet provide working hardware, recording software, annotation tools, or verified training integrations.

captureego aims to support the journey from recording natural human hand operations to producing training datasets in a local environment. The planned scope includes head- or chest-mounted capture, local recording, locally usable post-processing and annotation, raw-data transfer to another device on the same LAN, and data governance and dataset production on that compute device.

项目面向人自然使用双手操作的第一视角数据采集。当前确认的是以下产品范围，具体行为、实现方式和验收标准将在讨论后逐步确定。

| 产品范围 | 期望结果 |
| --- | --- |
| 第一视角采集 | 使用头戴或胸戴设备记录自然双手操作 |
| 本地保存 | 在本地保存采集数据 |
| 本地后处理与标注 | 提供在本地环境可用的后处理和标注能力 |
| 局域网原始数据导出 | 将原始采集数据导出到同一局域网的另一台设备 |
| 算力设备上的数据治理 | 在接收数据的算力设备上组织和治理采集数据 |
| 数据集生产与导出 | 在算力设备上生产面向 WAM 等训练用途的数据集 |

“本地可用”尚未限定为在穿戴设备上运行；具体部署位置和完全断网时的能力边界仍需讨论。视频、手部轨迹和机器人动作的含义不同，不能以文件格式转换代替缺失的数据或未经验证的动作映射。

## Start here / 从这里开始

- [设计入口](design/README.md)
- [已确认的产品范围](design/product/scope.md)
- [客户提供的候选规格](design/product/customer-inputs.md)
- [数据处理与数据集生产的讨论边界](design/data/README.md)
- [接下来的设计讨论](design/discussion.md)
- [项目工作约定](AGENTS.md)

## Design approach / 设计方式

先讨论使用者、任务、交付结果和产品边界，再确定软硬件架构、接口、选型和验证方法。`design/` 内的 Markdown 是设计来源；已确认范围、候选方案、实现、测试和验收分别表述。

当前未确定相机组合、安装方式细节、计算平台、同步机制、协议、存储格式、标注算法、模型和训练格式版本。客户提供的性能指标是需求输入，不是已实现或已承诺的能力。

## Open-source scope and licensing / 开源范围与许可

开源方向已确定。软件、硬件设计、文档与示例数据的具体许可证尚待讨论，当前尚未配置 LICENSE；公开可见不等于已授予开源许可。

仓库用于设计及后续可公开的工程材料。真实采集数据、客户原始资料、个人信息、凭据和本地产生的数据集不应直接提交到仓库。后续公开示例数据时，应单独说明来源和许可。
