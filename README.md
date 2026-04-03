# Podcast Research System 播客投研系统

将英文投资/科技播客转化为可操作的投研情报。

```
监控 RSS 新节目 → 下载音频 → 转录 + 说话人分离 → 翻译为中文 → 五维投研分析
```

## 核心模块

| 模块 | 功能 | 命令 |
|------|------|------|
| `monitor.py` | 检查关注播客的新节目 | `python monitor.py` |
| `transcribe.py` | 音频转录 + 说话人分离 | `python transcribe.py <url>` |
| `translate.py` | 英文逐字稿 → 中文 | `python translate.py input.txt` |
| `analyze.py` | 五维投研分析 | `python analyze.py input.txt` |
| `pipeline.py` | 一键全流程 | `python pipeline.py run <url>` |

## 安装

```bash
pip install -r requirements.txt

# ffmpeg（Whisper 需要）
# macOS: brew install ffmpeg
# Ubuntu: sudo apt install ffmpeg
```

### 环境变量

```bash
# 翻译和分析需要（等你解决 API 问题后设置）
export ANTHROPIC_API_KEY='your-api-key'

# 说话人分离需要
export HF_TOKEN='your-huggingface-token'
# 需先在 HuggingFace 接受 pyannote/speaker-diarization-3.1 和
# pyannote/segmentation-3.0 的使用条款
```

## 使用方法

### 1. 每日简报：看看今天有什么新节目

```bash
# 检查所有关注播客的最新节目
python pipeline.py daily

# 检查最近 3 天的更新
python pipeline.py daily --days 3

# 只看投资类
python pipeline.py daily --category investment
```

输出示例：
```
# 播客投研日报 (2026-04-03)
共 5 集新节目

## 💰 投资
- [04-03] All-In Podcast (01:23:45)
  E230: AI Infrastructure Spending is Out of Control
  🔗 https://...

## 🔬 科技
- [04-02] No Priors
  The Future of AI Agents with ...
  🔗 https://...
```

### 2. 完整投研分析：一键处理单集播客

```bash
# 全流程：下载 → 转录 → 翻译 → 分析
python pipeline.py run "https://播客链接"

# 只转录不翻译不分析（API 没配好时用这个）
python pipeline.py transcribe "https://播客链接"

# 跳过翻译（播客本身是中文的）
python pipeline.py run "https://中文播客链接" --language zh --skip-translate
```

输出到 `output/` 目录：
```
output/
  Episode_Title_transcript.txt   ← 带说话人标签的英文逐字稿
  Episode_Title_zh.txt           ← 中文翻译
  Episode_Title_analysis.txt     ← 五维投研分析
```

### 3. 半自动模式（无 API 时）

```bash
# 只生成逐字稿
python pipeline.py transcribe "https://播客链接"

# 然后手动把逐字稿粘贴给 Claude Max 做翻译和分析
```

### 4. 单独使用各模块

```bash
# 单独检查 RSS
python monitor.py --days 7

# 单独转录
python transcribe.py "https://播客链接" --diarize --model medium -o transcript.txt

# 单独翻译
python translate.py transcript.txt -o translated.txt

# 单独分析
python analyze.py translated.txt -o analysis.txt
```

## 五维投研分析框架

对每期播客输出：

| 维度 | 回答的问题 |
|------|-----------|
| **核心结论** | 他们在押什么？看多/看空什么？ |
| **关键论据** | 为什么？数据和逻辑链是什么？ |
| **隐含假设** | 观点成立必须依赖哪些未明说的前提？ |
| **反证条件** | 如果错，会错在哪？什么信号意味着该撤？ |
| **未讨论问题** | 他们没说但你该问的是什么？ |

## 关注的播客

编辑 `podcasts.yaml` 添加或删除播客。当前列表：

**投资**: All-In, Invest Like the Best, Acquired, Prof G, Meb Faber, Capital Allocators, We Study Billionaires

**宏观**: Bloomberg Odd Lots, Morgan Stanley Thoughts on the Market

**科技**: Lex Fridman, a16z, BG2Pod, No Priors, Stratechery

**加密**: Bankless, The Chopping Block

## Whisper 模型选择

| 模型 | 大小 | 推荐场景 |
|------|------|----------|
| base | ~74 MB | 快速预览 |
| small | ~244 MB | 英文播客日常 |
| medium | ~769 MB | **推荐**，中英文均好 |
| large | ~1550 MB | 追求极致准确 |
