# 第一版可执行采集协议

状态：软件原型实现；使用合成 JPEG/IMU 和真实公开 EgoDex 单目 1080p 视频回放验证。尚未验证实体设备、持续双目吞吐、硬同步或断电存储硬件保证。详见[真实数据验证](../validation/2026-09-24-real-data.md)。

## 连续接收

设备先检查 PC `/api/v1/ready`，再创建 recording。每个包带全局连续序号、流 ID、原始传感器时间戳和采集相对纳秒时间戳。设备采集线程和发送线程独立运行；每产生一包就进入临时 outbox，发送线程持续取出上传。

PC 在 `recordings/<id>/chunks/<时间块编号>/<序号>.json` 存包；当前封装是含 base64 JPEG/PNG、六轴 IMU JSON 或带显式有效性的 tracking JSON 的可检查原型协议，后续可增加二进制/视频封装。分块只改变存储位置，不改变时间戳，也不是任务切分。

PC 完成文件 fsync、目录 fsync、SQLite FULL 事务提交后返回该包摘要和 durable ACK。设备只在确认 ID、序号和摘要全部匹配后释放包体。SQLite 保留小型摘要账本；已释放页可复用，文件不会每包主动收缩。因此缓存上限指未确认包体预算，不是整个 SQLite 文件的硬物理上限。

同一 ID 或序号重试必须有相同内容，否则返回冲突。录制结束消息冻结包数量、各序号摘要的总体摘要、结束时间及原因。结束消息可先于剩余包到达。全部包齐备、时间递增、摘要和文件验证通过后才变为 complete。

## 错误与恢复

- 开始时 PC 不可用：不开始采集。
- 采集中断网：继续写临时缓存，自动重试发送。
- 缓存达到预算：结束本次采集，原因 cache_full；保留已有包，恢复连接后只补传，不自动开始新录制。
- 进程异常退出：`capego resume <outbox>` 冻结未结束采集为 interrupted，并补传已有数据。
- 结束但包未齐：awaiting_data；校验失败：integrity_failed。都不能开始后处理。
- 操作系统/磁盘故障可能导致采集进程退出。原型不声称具备硬件掉电保护。

## 运行边界

默认仅监听本机。绑定 LAN 地址必须设置 CAPEGO_TOKEN，明确接收端允许的 Host。Bearer 用于受信任局域网原型；需要跨不可信网络时由部署方提供 TLS，不直接暴露公网。token 只通过环境变量配置。

参考命令：`capego serve --root runtime/pc`、`capego simulate --seconds 5`、`capego verify <id>`。接收后不会自动运行任何后处理。

## 公开数据回放扩展

协议 v1 新增 `origin=dataset`、`kind=tracking` 与 `codec=tracking_json`，用于数据源已提供的相机／双手估计。原有 RGB/IMU 数据不变；旧接收端不认识新增枚举，使用前须更新两端。每帧 tracking 要求自身时间戳与包头一致，缺失观测写 null 且 validity=false，四元数须归一化。21 关节语义和来源参考系随 calibration 保存。

EgoDex 导入并不是新传感器采集；原 MP4 解码后以 JPEG 传输，提供原文件哈希，只有单目 RGB，没有 IMU。后处理通过用户显式选择 `dataset_annotations` 将归档中的来源估计整理成独立处理版本，自动到达不触发处理。
