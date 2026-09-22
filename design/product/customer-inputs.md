# 客户候选规格

以下内容来自客户关注项的输入。它们尚未被确认成首版必达规格，也没有实现和测试证据。最低要求、优选能力、适用条件与测量方法需要逐步讨论。

## 原始输入

| 关注项 | 输入内容 |
| --- | --- |
| Viewpoint | Egocentric (first-person, head or chest-mounted). |
| Vision Setup | Hardware-synchronized stereo / dual-camera RGB. |
| Resolution & Frame Rate | Minimum 1080p (preferably 1920×1200) @ 30–60 FPS. |
| Field of View (FOV) | 120°–150°. |
| Sensor Streams | Hardware-synchronized 6-axis IMU timestamp-aligned to video frames (≤1–2 ms tolerance). |
| Format | H.265/AV1 or high-bitrate MP4 with raw telemetry logs (ROS2 bag, MCAP, HDF5, or CSV). |

## 需要澄清的口径

| 关注项 | 待澄清内容 |
| --- | --- |
| 双 RGB | 固定基线的彩色立体相机对，还是不同朝向的两路彩色相机；当前尚未决定 |
| 分辨率与帧率 | 是否按每路要求；最低档与优选档如何区分；同时采集、编码与落盘的持续条件 |
| FOV | 水平、垂直或对角视场；原始图像与矫正后有效视场；近距离操作覆盖 |
| 同步误差 | 左右曝光偏差与视频-IMU时间对齐误差分别如何定义；统计口径和测试条件 |
| 编码与格式 | 区分视频编码、容器、遥测数据组织和训练导出；不把列举的格式解释为全部必选 |

单路 RGB 配合双目灰度相机，不等同于双路 RGB；具体视觉配置尚未确定。

## 讨论时机

当前先明确[产品范围](scope.md)、使用者和数据集交付目标。以上口径在进入相关软硬件设计前澄清，本页暂不选择具体器件、算法或协议。
