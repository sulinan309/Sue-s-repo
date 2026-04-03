#!/usr/bin/env python3
"""播客转录工具 - 将播客音频链接转换为逐字稿"""

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


def transcribe_audio(audio_path: str, model_name: str, language: str | None) -> dict:
    """使用 Whisper 模型转录音频，返回转录结果"""
    print(f"正在加载 Whisper 模型: {model_name}")
    model = whisper.load_model(model_name)

    print("正在转录音频（这可能需要一些时间）...")
    start = time.time()

    options = {}
    if language:
        options["language"] = language

    result = model.transcribe(audio_path, **options)
    elapsed = time.time() - start
    print(f"转录完成 ({elapsed:.1f}s)")
    return result


def format_timestamp(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_transcript(result: dict, show_timestamps: bool) -> str:
    """将 Whisper 结果格式化为逐字稿文本"""
    lines = []
    for segment in result["segments"]:
        text = segment["text"].strip()
        if not text:
            continue
        if show_timestamps:
            ts = format_timestamp(segment["start"])
            lines.append(f"[{ts}] {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


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

    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. 下载音频
        try:
            audio_path, title = download_audio(args.url, tmpdir)
        except Exception as e:
            print(f"下载失败: {e}", file=sys.stderr)
            sys.exit(1)

        # 2. 转录
        try:
            result = transcribe_audio(audio_path, args.model, args.language)
        except Exception as e:
            print(f"转录失败: {e}", file=sys.stderr)
            sys.exit(1)

    # 3. 格式化输出
    transcript = format_transcript(result, show_timestamps=not args.no_timestamps)

    header = f"# {title}\n\n"
    full_output = header + transcript

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(full_output)
        print(f"\n逐字稿已保存到: {args.output}")
    else:
        print("\n" + "=" * 60)
        print(full_output)
        print("=" * 60)


if __name__ == "__main__":
    main()
