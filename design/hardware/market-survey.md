# Ego 采集硬件调研

> 调研日期：2026-09-24。状态：公开资料调研与选型建议，待用户评审。没有采购、拆机或实体测试。厂商指标、论文自报结果和 CapEgo 设计目标分别标注；公开在售不代表国内现货。

## 结论

建议 CapEgo 采用**头部传感器、腰部计算与电池、局域网 PC 正式保存**的分体结构。首台工程参考机优先评估 **ZED X Mini 广角版 + Jetson Orin NX + 可引出同步信号的 ZED Link 采集卡**，增加独立同步 IMU 验证链路。它的优势是双 RGB、全局快门、分辨率与帧率已有明确产品规格；不足是价格、头部重量和闭源依赖。它不是已验证满足全部要求的整机。

低成本开源路线保留 **AR0234 双目模块 + RK3588 + 同步 MCU/IMU**，但当前不能把传感器支持某个模式，写成整套模组、驱动、编码和传输已经支持。先完成一台工程参考机的数据闭环，再决定是否做该路线，可避免同时承担相机驱动、ISP、硬同步和数据系统四类风险。具体设计和预算见[参考设计提案](reference-design.md)。

## 比较依据

沿用[产品范围](../product/scope.md)与[持续采集保存规则](../system/overview.md)：自然双手操作、没有手套与夹爪、录制期间持续传输、PC 可靠保存后释放缓存、后处理人工启动。

[客户规格](../product/customer-inputs.md)仍是候选：每路至少 1080p，优选 1920×1200；30–60 FPS；双 RGB 硬同步；FOV 120°–150°；相机与六轴 IMU 时间对齐 1–2 ms。没有把这些全部默认为已冻结要求。

筛选顺序是：原始数据可取得 → 双 RGB 与时间语义符合 → 可持续采集 → 戴得住 → 可公开复现 → 成本。AI 算力和自带手部跟踪不能替代这些条件。

## 已调查的代表性方案

下面同时覆盖完整 ego 设备、消费设备改装、开源参考机和可搭建采集头的视觉模块。模块不等于完整佩戴设备；“不符合”仅针对当前候选目标，不表示该产品没有其他价值。

| 方案 | 官方或作者公开事实 | 与 CapEgo 的关系 | 判断 |
| --- | --- | --- | --- |
| Meta Project Aria Gen 2 | 一路 RGB，四路灰度 CV 相机，双 IMU；RGB 为滚动快门，H133°/V99°；典型 IMU 800 Hz。[官方规格](https://facebookresearch.github.io/projectaria_tools/gen2/technical-specs/device/hardware) | 适合借鉴标定、时间域和数据完整性；不是两路高分辨率 RGB，硬件也不能自由制造复现 | 研究参考，不作为首版 BOM |
| Apple Vision Pro / EgoDex | Apple 发布的 EgoDex 通过 Vision Pro 的 ARKit 采集视频和手部运动。[官方仓库](https://github.com/apple-aiml-research/ml-egodex) | 能证明 ego 数据用途；数据集开放不等于原始相机、IMU及采集权限都可用，也不等于开放硬件 | 作为数据与标注参考，首版不绑定 |
| Pupil Labs Neon | 单路场景 RGB 1600×1200@30，H103°/V77°/D128°；两路眼动相机；模块 7.3 g；官网起价 €6,250。[官方规格与价格](https://pupil-labs.com/products/neon/hardware) | 轻巧分体结构值得借鉴，但眼动相机不能当作环境双 RGB；模块重量不含完整佩戴系统 | 不适合当前成本和双目目标 |
| GoPro HERO13 Black 代表的运动相机 | 官方发布规格包括 5.3K60、电子防抖和更换镜头等能力。[厂商发布](https://investor.gopro.com/press-releases/press-release-details/2024/GoPro-Announces-Two-New-Cameras-The-399-HERO13-Black-and-the-199-HERO/default.aspx) | 易于记录视频，但本次未找到双机曝光与 IMU 同步满足本项目容差的完整证据；防抖/裁剪还需明确几何语义 | 可作视频对照，不作为硬同步参考机 |
| iPhone / Stera 2.0 / MobileEgo | 开源手机采集栈支持视频、位姿、IMU及 MCAP；作者说明 ARKit 会限制超广角使用，长时间运行有热问题。[作者说明](https://www.fpvlabs.ai/essays/stera-capture-app) | 复现软件路径方便；不是已证实的双 RGB 硬同步采集头；手机实时估计也须标为估计 | 入门适配方向，不替代主硬件 |
| Ego-OSCAR | 作者报告双全局快门 RGB，每路 1280×720@30、42 mm 基线、126° FOV；约 280 g，BOM 约 $200；默认录完上传。[论文](https://arxiv.org/html/2608.08285v1) | 最接近本项目的开放采集架构，但低于 1080p，传输行为也不同 | 借鉴同步、看门狗和装配经验，不照搬 |
| ZED X Mini 广角版 | 双 RGB 全局快门，每路 1920×1200@30/60；50 mm 基线；H110°/V80°/D120°；151 g，IMU 200 Hz。[规格](https://docs.stereolabs.com/docs/products/cameras/zedx/specifications) | 图像指标贴近目标；需 Jetson/GMSL2，不能直接接普通 USB；内置 IMU 对齐精度仍须核验 | 首台工程参考机优先候选 |
| ZED X Nano | 双 RGB 1920×1200@60，75 g，18 mm 基线；H92°/V65°/D102°。[规格](https://docs.stereolabs.com/docs/products/cameras/zedx/specifications) | 更轻，但视场明显缩小，短基线也改变近场几何能力 | 不能仅因轻便替换 Mini |
| Luxonis OAK-D SR | 双 OV9782 彩色全局快门、800p、20 mm 基线、H80°/V55°/D89.5°，含 IMU。[官方资料](https://docs.luxonis.com/hardware/products/OAK-D%20SR) | 确实是双 RGB，但分辨率和视场不足；不要与其他 OAK-D 配置混为一谈 | 排除当前主规格 |
| Luxonis AR0234 模块化路线 | 官方传感器页列出彩色全局快门、1920×1200@60；OAK-FFC-AR0234-M12 标为 WIP。[传感器资料](https://docs.luxonis.com/hardware/sensors/AR0234) | 适合继续跟踪；传感器模式不等于模块可采购、双路输出与同步已验证 | 储备候选，暂不写入确定 BOM |
| Arducam AR0234 双目 / GMSL2 | 官方选型表中 B0611 为 3840×1200 拼接双目、30 FPS、板载 ISP；镜头选项包括 H125°，默认 H98°。[选型表](https://docs.arducam.com/GMSL-Camera-Solution/RapidRange-G2-GMSL-Camera/Introduction/) | 可覆盖更宽水平视场；但默认镜头不满足，60 FPS 不应据传感器能力推断。需核对具体板卡、同步引脚、帧号、驱动和重量 | 若要求水平 ≥120°，重点评估此路线 |
| Orbbec Gemini 335 | 双 IR 深度加单 RGB；RGB 1920×1080@30，含 IMU。[产品规格](https://www.orbbec.com/products/stereo-vision-camera/gemini-335/) | 易获得 RGB-D 数据，但不是双环境 RGB | 可作几何对照，不符合双 RGB 主规格 |
| RealSense D455 | 主动 IR 双目与单 RGB；RGB 1280×800@30、全局快门，含 IMU。[官方规格](https://www.realsenseai.com/products/real-sense-depth-camera-d455f/) | 常见深度采集模块，但 RGB 路数、分辨率与视场都不同 | 不作为主参考机 |

以上不是销量或市场份额排名。未获得厂商报价、样机或独立复测，不对库存、长期供货和量产良率作保证。

## 最值得借鉴和需要警惕的证据

### Ego-OSCAR：开放架构很有参考价值，论文指标不能直接迁移

作者用相机曝光信号、ESP32 和 IMU 建立时间关联，报告经校正后约 700 µs 的视觉惯性残差；也披露前重下滑、散热和部分轨迹失败。这个结果不能等同于每帧硬同步最大误差，更不能推导 CapEgo 的三维手部精度。[论文方法与评估](https://arxiv.org/html/2608.08285v1)

公开仓库包含 MCU 固件、Radxa 采集与诊断程序，并明确需要支持 Rockchip MPP 的 FFmpeg。采集主板、编码驱动及系统镜像必须一起锁定；只买同款芯片不足以复现。CAD/搭建资料还链接到仓库外，应在复用前逐项检查文件完整性及许可。[作者仓库](https://github.com/fpv-labs/ego-oscar)

### ZED：曝光同步、时间戳和 IMU 取样间隔要分开

厂商技术回复明确区分图像时间戳与曝光开始/中点，没有提供可直接拿来验收的时间戳抖动上限；取最近 IMU 样本时，200 Hz 的半周期为 2.5 ms。插值可以在指定时刻生成估计，但不能证明底层时钟误差变小。[厂商技术回复](https://community.stereolabs.com/t/pre-purchase-technical-evaluation-zed-2i-vs-zed-x-timestamping-tov-accuracy/11592/2)

有可执行的改进路径：ZED Link Mono 的 TRIG_OUT 上升沿对应曝光结束，可接到独立 MCU 的硬件计时输入。输出电平为 3.75 V ±12%，不能不核对电气条件就直连 3.3 V 输入；应做电平转换。这个接口让时间链路可测，但仍需解决丢帧后的脉冲与帧号匹配。[同步接口文档](https://docs.stereolabs.com/docs/products/embedded/zed-link-capture-card/gmsl2/zed-link-mono/zed-link-mono-gpio-triggering)

### 原始流访问和离线运行比附带 AI 功能更重要

Aria、Vision Pro、手机和工业相机都可以产生有价值的 ego 数据，但开放数据集、开放应用代码、可读取原始流、可离线运行、可复制硬件是不同层次。本项目要公开自有装配、同步固件、采集软件、标定及数据契约；采用商用模组时如实记录闭源依赖。不能把 CapEgo 的 Apache-2.0 延伸到第三方 SDK、固件或机械文件。

## 三条路线的取舍

| 路线 | 优点 | 主要代价 | 建议 |
| --- | --- | --- | --- |
| 现成双目 + Jetson + 独立同步 IMU | 分辨率和双目接口明确，较快得到真实样本，可测量同步链路 | 首台成本高、头部较重、依赖厂商驱动，仍有同步开发 | **首台推荐**，优先降低数据链路的不确定性 |
| AR0234 + RK3588 + MCU/IMU | 可优化成本、尺寸、镜头与开放接口 | 跨厂商相机/ISP/编码适配，供应和同步证据不足 | 首台闭环后再决定，不并行承诺两套产品 |
| 手机 / 运动相机 / 现成低分辨率开源设备 | 起步便捷，能够采集视频测试流程 | 必须放宽双 RGB、分辨率或同步目标 | 仅在用户主动调整目标时改为主线 |

首台高成本不意味着社区版本永久高成本。反过来，开源项目也不应从第一天同时承担自制双目板、相机驱动、硬件编码、轻量外壳和训练链路的所有风险。

## 价格使用口径

- ZED X Mini 官方起价 **$549**，ZED X Nano **$399**，都只是相机；不含 Jetson、采集卡、电池和装配。[官方在售列表](https://www.stereolabs.com/store/collections/cameras)
- Neon 官网起价 **€6,250**，不按“单个 7.3 g 模组价格”理解。[官方页面](https://pupil-labs.com/products/neon/hardware)
- Ego-OSCAR 的约 **$200** 是作者公布的特定配置 BOM，既不是国内含税成交价，也不是 1080p 版本报价。[论文](https://arxiv.org/html/2608.08285v1)
- CapEgo 预算为设计预估，见下一份文档。不同币种不在没有汇率依据时混算；采购前按同一税费、运费、供货和附件口径报价。

## 仍须补齐的供应商资料

这些是样机选型的核验项，本次没有代用户发送询价或联系厂商。

1. 精确 SKU、镜头、主板、采集卡、线缆、JetPack/驱动/SDK 兼容组合和供货期。
2. 双路原始/编码输出模式、曝光和帧号字段、左右曝光锁定方式、全部 IMU 样本读取方法。
3. 同步引脚电平、曝光对应边沿、触发到曝光延迟及抖动、丢帧后如何重新建立映射。
4. 标定获取方式，以及完成首次安装后断开互联网能否启动并完整采集。
5. 开源项目可分发的驱动、安装包、固件、CAD 和标定工具范围。

本次没有找到一款经公开证据完整覆盖“开放复现 + 双 1200p60 RGB + 宽视场 + 1–2 ms IMU 对齐 + 持续可靠 LAN 归档 + 轻量低价”的现成产品。这个结论限定于本次核查范围，不声称市场上绝对不存在。
