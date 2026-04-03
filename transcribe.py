#!/usr/bin/env python3
"""播客转录工具 - 将播客音频链接转换为逐字稿"""

import argparse
import os
import sys
import tempfile
import time

import whisper
import yt_dlp


def download_audio(url: str, output_dir: str) -> str:
    """从 URL 下载音频文件，返回下载后的文件路径"""
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

    print(f"正在下载音频: {url}")
    start = time.time()

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "未知标题")

    audio_path = os.path.join(output_dir, "audio.mp3")
    if not os.path.exists(audio_path):
        # 某些情况下后缀可能不同，找到实际文件
        for f in os.listdir(output_dir):
            if f.startswith("audio."):
                audio_path = os.path.join(output_dir, f)
                break

    elapsed = time.time() - start
    print(f"下载完成: {title} ({elapsed:.1f}s)")
    return audio_path, title


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


def main():
    parser = argparse.ArgumentParser(
        description="播客转录工具 - 将播客音频链接转换为逐字稿"
    )
    parser.add_argument("url", help="播客音频链接（支持 YouTube、直链等）")
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
