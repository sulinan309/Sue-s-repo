# Podcast Transcription Tool

将播客音频转换为逐字稿的命令行工具。

## 功能

- 支持多种播客平台:
  - **小宇宙** (`xiaoyuzhoufm.com/episode/...`)
  - **Apple Podcasts** (`podcasts.apple.com/...`)
  - **YouTube** 及其他 yt-dlp 支持的平台
  - 任意音频直链
- 使用 OpenAI Whisper 开源模型进行语音识别
- 支持多语言（中文、英文等）
- 输出纯文本逐字稿，附带时间戳
- **`--polish` 模式**：使用 Claude 将逐字稿整理为可读的口述长文（区分说话人、合并碎片句、去除口头禅）

## 安装

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 安装 ffmpeg（Whisper 需要）
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows
# 从 https://ffmpeg.org/download.html 下载并添加到 PATH
```

## 使用方法

```bash
# 小宇宙播客
python transcribe.py "https://www.xiaoyuzhoufm.com/episode/xxx"

# Apple Podcasts
python transcribe.py "https://podcasts.apple.com/cn/podcast/xxx/id123?i=456"

# YouTube 或其他平台
python transcribe.py <播客音频链接>

# 指定 Whisper 模型大小（tiny/base/small/medium/large）
python transcribe.py <链接> --model medium

# 指定输出文件
python transcribe.py <链接> -o output.txt

# 指定语言（跳过自动检测，加快速度）
python transcribe.py <链接> --language zh

# 不显示时间戳
python transcribe.py <链接> --no-timestamps

# 整理为可读口述长文（需要 ANTHROPIC_API_KEY）
export ANTHROPIC_API_KEY='your-api-key'
python transcribe.py <链接> --polish --model medium --language zh -o article.txt
```

## 模型选择指南

| 模型 | 大小 | 速度 | 准确度 | 适用场景 |
|------|------|------|--------|----------|
| tiny | ~39 MB | 最快 | 较低 | 快速预览 |
| base | ~74 MB | 快 | 一般 | 日常使用 |
| small | ~244 MB | 中等 | 较好 | 推荐入门 |
| medium | ~769 MB | 较慢 | 好 | 推荐中文 |
| large | ~1550 MB | 最慢 | 最好 | 追求精度 |

## 输出示例

### 逐字稿模式（默认）

```
[00:00:00] 大家好，欢迎收听本期播客。
[00:00:05] 今天我们要聊的话题是人工智能的最新发展。
[00:00:12] 首先让我介绍一下今天的嘉宾。
...
```

### 口述长文模式（`--polish`）

```
**主持人**：大家好，欢迎收听本期播客。今天我们要聊的话题是人工智能的最新发展。
首先让我介绍一下今天的嘉宾，他是某某公司的 CTO 张三。

**张三**：大家好，很高兴来到这个节目。其实我最近一直在关注大语言模型的进展，
特别是在代码生成这个方向上，变化非常大。

**主持人**：对，这也是我们今天想深入聊的。你能不能先给大家讲讲，从你的视角来看，
过去一年最大的变化是什么？
...
```
