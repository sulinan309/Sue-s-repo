#!/usr/bin/env python3
"""播客转录工具 - 将播客音频链接转换为带说话人标注的逐字稿"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
import urllib.error

import whisper
import yt_dlp


# ── 平台解析器 ──────────────────────────────────────────────


def _http_get(url: str, headers: dict | None = None) -> str:
    """简单的 HTTP GET 请求，返回响应文本"""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def extract_xiaoyuzhou(url: str) -> tuple[str, str] | None:
    """解析小宇宙播客链接，返回 (音频URL, 标题) 或 None

    支持的链接格式:
      - https://www.xiaoyuzhoufm.com/episode/{eid}
    """
    match = re.match(r"https?://(?:www\.)?xiaoyuzhoufm\.com/episode/(\w+)", url)
    if not match:
        return None

    eid = match.group(1)
    print(f"检测到小宇宙播客，正在解析 episode: {eid}")

    # 方式1: 通过页面 HTML 中的 JSON 数据提取
    try:
        html = _http_get(url)

        # 小宇宙页面在 <script> 中嵌入 __NEXT_DATA__ JSON
        m = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>', html, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            # 遍历 JSON 结构找到 episode 数据
            episode = _find_episode_in_json(data)
            if episode:
                audio_url = episode.get("enclosure", {}).get("url") or episode.get("mediaKey")
                title = episode.get("title", "未知标题")
                if audio_url:
                    # mediaKey 需要拼接完整 URL
                    if not audio_url.startswith("http"):
                        audio_url = f"https://media.xyzcdn.net/{audio_url}"
                    return audio_url, title

        # 方式2: 从 meta 标签提取音频链接
        m = re.search(r'<meta\s+property="og:audio"\s+content="([^"]+)"', html)
        if m:
            audio_url = m.group(1)
            title_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
            title = title_m.group(1) if title_m else "未知标题"
            return audio_url, title

    except urllib.error.URLError as e:
        print(f"小宇宙页面请求失败: {e}")

    # 方式3: 尝试通过 API 获取
    try:
        api_url = f"https://api.xiaoyuzhoufm.com/v1/episode/detail?eid={eid}"
        resp_text = _http_get(api_url, headers={"Referer": "https://www.xiaoyuzhoufm.com/"})
        data = json.loads(resp_text)
        audio_url = data.get("data", {}).get("enclosure", {}).get("url", "")
        title = data.get("data", {}).get("title", "未知标题")
        if audio_url:
            return audio_url, title
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"小宇宙 API 请求失败: {e}")

    return None


def _find_episode_in_json(obj, depth=0):
    """递归查找 JSON 中的 episode 数据（包含 enclosure 或 mediaKey 字段）"""
    if depth > 10:
        return None
    if isinstance(obj, dict):
        if "enclosure" in obj and "title" in obj:
            return obj
        if "mediaKey" in obj and "title" in obj:
            return obj
        for v in obj.values():
            result = _find_episode_in_json(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_episode_in_json(item, depth + 1)
            if result:
                return result
    return None


def extract_apple_podcasts(url: str) -> tuple[str, str] | None:
    """解析 Apple Podcasts 链接，返回 (音频URL, 标题) 或 None

    支持的链接格式:
      - https://podcasts.apple.com/{locale}/podcast/{name}/id{pid}?i={eid}
      - https://podcasts.apple.com/podcast/id{pid}?i={eid}
    """
    match = re.match(r"https?://podcasts\.apple\.com/", url)
    if not match:
        return None

    print("检测到 Apple Podcasts，正在解析...")

    # 从 URL 中提取 podcast ID 和 episode ID
    pod_id_m = re.search(r'/id(\d+)', url)
    ep_id_m = re.search(r'[?&]i=(\d+)', url)

    if not pod_id_m:
        print("无法从 URL 中提取 Podcast ID")
        return None

    pod_id = pod_id_m.group(1)
    ep_id = ep_id_m.group(1) if ep_id_m else None

    # 方式1: 通过 iTunes Lookup API 获取 Feed URL，再从 RSS 提取音频
    try:
        lookup_url = f"https://itunes.apple.com/lookup?id={pod_id}&entity=podcast"
        resp_text = _http_get(lookup_url)
        data = json.loads(resp_text)
        results = data.get("results", [])
        if not results:
            print("iTunes API 未返回结果")
            return None

        feed_url = results[0].get("feedUrl")
        podcast_name = results[0].get("collectionName", "未知播客")

        if not feed_url:
            print("未找到 RSS Feed URL")
            return None

        print(f"正在解析 RSS Feed: {podcast_name}")
        return _parse_rss_feed(feed_url, ep_id)

    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"iTunes API 请求失败: {e}")

    # 方式2: 直接从页面提取
    try:
        html = _http_get(url)

        # 从 schema.org JSON-LD 提取
        for m in re.finditer(r'<script\s+type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
            try:
                ld = json.loads(m.group(1))
                if isinstance(ld, list):
                    ld = ld[0]
                audio_url = ld.get("associatedMedia", {}).get("contentUrl")
                if not audio_url:
                    audio_url = ld.get("url")
                title = ld.get("name", "未知标题")
                if audio_url and audio_url.endswith((".mp3", ".m4a", ".aac")):
                    return audio_url, title
            except json.JSONDecodeError:
                continue

        # 从 meta 标签提取
        m = re.search(r'<meta\s+name="apple-itunes-app"\s+content="[^"]*assetUrl=([^&"]+)', html)
        if m:
            audio_url = urllib.parse.unquote(m.group(1))
            title_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
            title = title_m.group(1) if title_m else "未知标题"
            return audio_url, title

    except urllib.error.URLError as e:
        print(f"Apple Podcasts 页面请求失败: {e}")

    return None


def _parse_rss_feed(feed_url: str, target_ep_id: str | None) -> tuple[str, str] | None:
    """解析 RSS Feed 获取音频链接和标题

    如果提供了 target_ep_id，尝试匹配对应单集；否则返回最新一集。
    """
    try:
        xml = _http_get(feed_url)
    except urllib.error.URLError as e:
        print(f"RSS Feed 请求失败: {e}")
        return None

    # 提取所有 <item> 条目
    items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
    if not items:
        print("RSS Feed 中未找到条目")
        return None

    for item in items:
        # 提取音频 URL
        enclosure_m = re.search(r'<enclosure[^>]+url="([^"]+)"', item)
        if not enclosure_m:
            continue
        audio_url = enclosure_m.group(1)

        # 提取标题
        title_m = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item)
        title = title_m.group(1).strip() if title_m else "未知标题"

        # 如果有目标 episode ID，尝试通过 GUID 或其他方式匹配
        if target_ep_id:
            guid_m = re.search(r'<guid[^>]*>(.*?)</guid>', item)
            guid = guid_m.group(1) if guid_m else ""
            # Apple 的 episode ID 可能出现在 guid 或 URL 中
            if target_ep_id in guid or target_ep_id in item:
                return audio_url, title
        else:
            # 没有指定 episode ID，返回第一集（最新）
            return audio_url, title

    # 如果指定了 ep_id 但没匹配到，返回最新一集
    if target_ep_id and items:
        enclosure_m = re.search(r'<enclosure[^>]+url="([^"]+)"', items[0])
        title_m = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', items[0])
        if enclosure_m:
            audio_url = enclosure_m.group(1)
            title = title_m.group(1).strip() if title_m else "未知标题"
            print(f"未精确匹配到 episode ID {target_ep_id}，使用最新一集")
            return audio_url, title

    return None


# ── 平台解析器注册 ──────────────────────────────────────────

EXTRACTORS = [
    extract_xiaoyuzhou,
    extract_apple_podcasts,
]


# ── 下载 ────────────────────────────────────────────────────


def download_with_url(audio_url: str, title: str, output_dir: str) -> tuple[str, str]:
    """直接通过音频 URL 下载文件"""
    print(f"正在下载音频: {title}")
    start = time.time()

    # 根据 URL 判断扩展名
    ext = "mp3"
    for candidate in (".m4a", ".aac", ".wav", ".ogg", ".mp3"):
        if candidate in audio_url.lower():
            ext = candidate.lstrip(".")
            break

    audio_path = os.path.join(output_dir, f"audio.{ext}")
    req = urllib.request.Request(audio_url)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    with urllib.request.urlopen(req, timeout=300) as resp:
        total = resp.headers.get("Content-Length")
        total = int(total) if total else None
        downloaded = 0
        with open(audio_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  下载进度: {pct:.1f}% ({downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB)", end="", flush=True)

    elapsed = time.time() - start
    if total:
        print()
    print(f"下载完成: {title} ({elapsed:.1f}s)")
    return audio_path, title


def download_with_ytdlp(url: str, output_dir: str) -> tuple[str, str]:
    """使用 yt-dlp 下载音频"""
    output_template = os.path.join(output_dir, "audio.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    print(f"正在通过 yt-dlp 下载音频: {url}")
    start = time.time()

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "未知标题")

    audio_path = os.path.join(output_dir, "audio.mp3")
    if not os.path.exists(audio_path):
        for f in os.listdir(output_dir):
            if f.startswith("audio."):
                audio_path = os.path.join(output_dir, f)
                break

    elapsed = time.time() - start
    print(f"下载完成: {title} ({elapsed:.1f}s)")
    return audio_path, title


def download_audio(url: str, output_dir: str) -> tuple[str, str]:
    """下载音频：先尝试平台解析器，再回退到 yt-dlp"""
    # 尝试各平台解析器
    for extractor in EXTRACTORS:
        result = extractor(url)
        if result:
            audio_url, title = result
            print(f"解析成功: {title}")
            print(f"音频链接: {audio_url[:80]}...")
            return download_with_url(audio_url, title, output_dir)

    # 回退到 yt-dlp
    return download_with_ytdlp(url, output_dir)


# ── 转录 ────────────────────────────────────────────────────


def transcribe_audio(
    audio_path: str, model_name: str, language: str | None, diarize: bool = False,
    hf_token: str | None = None, num_speakers: int | None = None,
) -> list[dict]:
    """转录音频，返回片段列表。

    每个片段为 {"start": float, "end": float, "text": str, "speaker": str|None}。
    当 diarize=True 时，使用 pyannote.audio 进行说话人分离并为每个片段标注 speaker。
    """
    print(f"正在加载 Whisper 模型: {model_name}")
    model = whisper.load_model(model_name)

    print("正在转录音频（这可能需要一些时间）...")
    start = time.time()

    options = {}
    if language:
        options["language"] = language

    whisper_result = model.transcribe(audio_path, **options)
    elapsed = time.time() - start
    print(f"转录完成 ({elapsed:.1f}s)")

    # 构建片段列表
    segments = []
    for seg in whisper_result["segments"]:
        text = seg["text"].strip()
        if not text:
            continue
        segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": text,
            "speaker": None,
        })

    # 说话人分离
    if diarize:
        segments = _assign_speakers(audio_path, segments, hf_token, num_speakers)

    return segments


def _assign_speakers(
    audio_path: str, segments: list[dict],
    hf_token: str | None, num_speakers: int | None,
) -> list[dict]:
    """使用 pyannote.audio 进行说话人分离，将 speaker 标签写入每个片段"""
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        print("错误: 说话人分离需要安装 pyannote.audio", file=sys.stderr)
        print("  pip install pyannote.audio", file=sys.stderr)
        sys.exit(1)

    if not hf_token:
        hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("错误: 说话人分离需要 HuggingFace token", file=sys.stderr)
        print("  export HF_TOKEN='your-huggingface-token'", file=sys.stderr)
        print("  并在 https://huggingface.co/pyannote/speaker-diarization-3.1 接受使用条款", file=sys.stderr)
        sys.exit(1)

    print("正在进行说话人分离...")
    start = time.time()

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )

    diarize_params = {}
    if num_speakers:
        diarize_params["num_speakers"] = num_speakers

    diarization = pipeline(audio_path, **diarize_params)

    # 构建说话人时间轴: [(start, end, speaker), ...]
    speaker_timeline = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        speaker_timeline.append((turn.start, turn.end, speaker))

    # 为每个 Whisper 片段分配说话人（取重叠最多的）
    for seg in segments:
        seg_start = seg["start"]
        seg_end = seg["end"]
        best_speaker = None
        best_overlap = 0.0

        for sp_start, sp_end, speaker in speaker_timeline:
            overlap_start = max(seg_start, sp_start)
            overlap_end = min(seg_end, sp_end)
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker

        seg["speaker"] = best_speaker or "UNKNOWN"

    # 重命名 speaker 标签为更友好的名字 (SPEAKER_00 → 说话人1)
    unique_speakers = []
    for seg in segments:
        if seg["speaker"] not in unique_speakers:
            unique_speakers.append(seg["speaker"])

    speaker_map = {}
    for i, sp in enumerate(unique_speakers):
        speaker_map[sp] = f"说话人{i + 1}"

    for seg in segments:
        seg["speaker"] = speaker_map.get(seg["speaker"], seg["speaker"])

    elapsed = time.time() - start
    print(f"说话人分离完成，识别到 {len(unique_speakers)} 位说话人 ({elapsed:.1f}s)")

    return segments


def format_timestamp(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_transcript(segments: list[dict], show_timestamps: bool) -> str:
    """将片段列表格式化为逐字稿文本

    如果片段含有 speaker 信息，会按说话人分段，同一人连续发言合并为一段。
    """
    has_speakers = any(seg["speaker"] for seg in segments)

    if not has_speakers:
        # 无说话人信息，简单逐行输出
        lines = []
        for seg in segments:
            if show_timestamps:
                ts = format_timestamp(seg["start"])
                lines.append(f"[{ts}] {seg['text']}")
            else:
                lines.append(seg["text"])
        return "\n".join(lines)

    # 有说话人信息：按说话人分段，同一人连续发言合并
    blocks = []
    current_speaker = None
    current_texts = []
    current_start = 0.0

    for seg in segments:
        speaker = seg["speaker"]
        if speaker != current_speaker:
            # 保存上一段
            if current_texts:
                blocks.append((current_speaker, current_start, " ".join(current_texts)))
            current_speaker = speaker
            current_texts = [seg["text"]]
            current_start = seg["start"]
        else:
            current_texts.append(seg["text"])

    # 保存最后一段
    if current_texts:
        blocks.append((current_speaker, current_start, " ".join(current_texts)))

    lines = []
    for speaker, start, text in blocks:
        if show_timestamps:
            ts = format_timestamp(start)
            lines.append(f"[{ts}] **{speaker}**：{text}")
        else:
            lines.append(f"**{speaker}**：{text}")
    return "\n\n".join(lines)


# ── 主程序 ──────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="播客转录工具 - 将播客音频链接转换为逐字稿"
    )
    parser.add_argument(
        "url",
        help="播客音频链接（支持小宇宙、Apple Podcasts、YouTube 等）",
    )
    parser.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper 模型大小 (默认: base)",
    )
    parser.add_argument("-o", "--output", help="输出文件路径（默认打印到终端）")
    parser.add_argument("--language", help="指定语言代码，如 zh/en（默认自动检测）")
    parser.add_argument(
        "--no-timestamps", action="store_true", help="不显示时间戳"
    )
    parser.add_argument(
        "--diarize", action="store_true",
        help="启用说话人分离，识别不同说话人（需要 HF_TOKEN 和 pyannote.audio）",
    )
    parser.add_argument(
        "--hf-token", help="HuggingFace token（也可通过 HF_TOKEN 环境变量设置）",
    )
    parser.add_argument(
        "--num-speakers", type=int,
        help="指定说话人数量（可选，不指定则自动检测）",
    )

    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. 下载音频
        try:
            audio_path, title = download_audio(args.url, tmpdir)
        except Exception as e:
            print(f"下载失败: {e}", file=sys.stderr)
            sys.exit(1)

        # 2. 转录（+ 可选说话人分离）
        try:
            segments = transcribe_audio(
                audio_path, args.model, args.language,
                diarize=args.diarize, hf_token=args.hf_token,
                num_speakers=args.num_speakers,
            )
        except Exception as e:
            print(f"转录失败: {e}", file=sys.stderr)
            sys.exit(1)

    # 3. 格式化逐字稿
    transcript = format_transcript(segments, show_timestamps=not args.no_timestamps)
    full_output = f"# {title}\n\n{transcript}"

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(full_output)
        print(f"\n逐字稿已保存到: {args.output}")
        print("提示: 可将逐字稿粘贴给 Claude 整理为可读的口述长文")
    else:
        print("\n" + "=" * 60)
        print(full_output)
        print("=" * 60)


if __name__ == "__main__":
    main()
