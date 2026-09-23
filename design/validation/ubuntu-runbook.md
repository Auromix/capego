# Ubuntu 24.04 / 云桌面测试方法

云电脑里获得终端后执行。此流程不需要实体采集设备，也不需要把云账号或密码写入任何文件。只创建项目目录与 Python 虚拟环境。

## 基础流程

系统需要 Git、Python 3.11+、venv。Ubuntu 24.04 默认 Python 3.12；若没有 venv，由系统管理员安装相应软件包。

```bash
git clone https://github.com/Auromix/capego.git
cd capego
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,export]'
capego doctor
pytest -q
python scripts/demo_pipeline.py --root runtime/ubuntu-demo --egowam
```

这个 demo 自行启动本机 HTTP 接收服务，持续发送双路 RGB 与 IMU，主动处理、创建快照并导出，然后停止自己的接收服务。`runtime/ubuntu-demo/demo-report.json` 提供结果路径。

需要查看工作台时运行 `capego serve --root runtime/ubuntu-demo/pc`，在云桌面自己的浏览器访问 `http://localhost:8765`。

## EgoWAM 实际训练入口验证

```bash
python -m pip install -e '.[training]' -r requirements-upstream-smoke.txt
git clone https://github.com/GaTech-RL2/EgoWAM.git runtime/EgoWAM
git -C runtime/EgoWAM checkout c87617fe37a6ed6a951e6b176ad552200c425c93
python scripts/validate_egowam.py --upstream runtime/EgoWAM \
  --demo-report runtime/ubuntu-demo/demo-report.json \
  --output runtime/validation/egowam-cpu.json
```

若 `capego doctor` 显示 CUDA 可用，再将验证命令增加 `--device cuda`，输出为另一个报告文件。驱动/CUDA/PyTorch 兼容性由该设备的实际环境验证；本仓库不会擅自升级系统驱动。

## 本地 VLM

```bash
python -m pip install -e '.[vlm]'
# 首次准备需要联网；确认磁盘容量后，将模型下载到项目 models/qwen2.5-vl。
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-VL-3B-Instruct', revision='66285546d2b821cf421d4f5eb2576359d3770cd3', local_dir='models/qwen2.5-vl', allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.jinja'])"
capego process RECORDING_ID --root runtime/ubuntu-demo/pc --backend local_vlm
```

正式推理只从本地目录读取，禁止自动下载与远程代码。可设置 `CAPEGO_MODEL_ROOT` 更换本地模型根目录。模型采样最多 4 帧做语义标注，全部输出需要检查；3D 几何仍由独立算法提供。

## 如何提供远程测试入口

现有授权只给出了无影桌面登录账号。可选入口是已登录且能操作的 Web/客户端终端，或组织已经配置好的 SSH 地址/端口与授权方式，或具备云助手远程命令权限的管理员会话。不需要开放公网 SSH，也不要把密码提交进仓库。

阿里云官方说明：[发送远程命令](https://help.aliyun.com/zh/wuying-workspace/user-guide/send-remote-commands)、[Web 客户端](https://help.aliyun.com/zh/wtc/user-guide/web-client)、[CLI 凭据配置](https://help.aliyun.com/zh/cli/other-configure-command-operations)。
