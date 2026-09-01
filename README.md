# JanitorJAV

JanitorJAV 是一个面向 JAV 媒体库的本地批量扫描与维护工具。

第一阶段用于扫描媒体库中的视频，在固定抽样帧中通过本地 OCR 检测网址或 IP 地址，并将疑似广告、短视频、旧格式和处理异常等情况分别标记，供用户在本地 Web 界面中审核和隔离。

第一阶段不会自动删除媒体文件，也不提供永久删除功能。

## 当前状态

项目已进入开发阶段。当前已完成第一批可测试的扫描核心：

- MDC 资产、CD 和 VR 文件名解析及分组；
- 固定秒数与百分位抽帧点计算；
- 点分文本、两字符后缀和 IPv4 检测；
- 固定同级隔离目录的路径校验；
- ffprobe 元数据和 FFmpeg 抽帧适配层；
- 本地 OCR 引擎协议和扫描标签管线；
- 可恢复 JSONL 读写基础。

Windows CUDA OCR、任务调度和 Web 审核界面仍在开发中。

## 本地开发

需要 Python 3.11 或更高版本。

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

## 文档

- [V1 产品与技术规格](docs/v1-specification.md)
- [V1 需求访谈记录](docs/requirements-interview-log.md)
- [使用指南](docs/user-guide.md)
