#!/usr/bin/env python3
"""播客投研系统 - 全流程管道

一键完成：下载 → 转录 → 说话人分离 → 翻译 → 投研分析
"""

import argparse
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from analyze import analyze_transcript
from monitor import check_feeds, format_episode_list, load_podcasts
from transcribe import download_audio, format_transcript, transcribe_audio
from translate import translate_transcript


def run_pipeline(
    url: str,
    output_dir: str = "output",
    whisper_model: str = "medium",
    language: str | None = None,
    diarize: bool = True,
    hf_token: str | None = None,
    num_speakers: int | None = None,
    skip_translate: bool = False,
    skip_analyze: bool = False,
) -> dict:
    """执行完整的投研管道

    Returns:
        包含各步骤输出文件路径的字典
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        # ── 步骤 1: 下载音频 ──
        print("\n" + "=" * 60)
        print("📥 步骤 1/4: 下载音频")
        print("=" * 60)
        audio_path, title = download_audio(url, tmpdir)

        # 生成安全的文件名前缀
        safe_title = _safe_filename(title)
        results["title"] = title

        # ── 步骤 2: 转录 + 说话人分离 ──
        print("\n" + "=" * 60)
        print("🎙️ 步骤 2/4: 转录 + 说话人分离")
        print("=" * 60)
        segments = transcribe_audio(
            audio_path, whisper_model, language,
            diarize=diarize, hf_token=hf_token, num_speakers=num_speakers,
        )

    transcript = format_transcript(segments, show_timestamps=True)
    transcript_file = os.path.join(output_dir, f"{safe_title}_transcript.txt")
    full_transcript = f"# {title}\n\n{transcript}"
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(full_transcript)
    print(f"逐字稿已保存: {transcript_file}")
    results["transcript"] = transcript_file

    # ── 步骤 3: 翻译 ──
    if not skip_translate:
        print("\n" + "=" * 60)
        print("🌐 步骤 3/4: 英文 → 中文翻译")
        print("=" * 60)

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("⚠️  未设置 ANTHROPIC_API_KEY，跳过翻译")
            print("   逐字稿已保存，可手动粘贴给 Claude 翻译")
        else:
            translated = translate_transcript(transcript, api_key)
            translate_file = os.path.join(output_dir, f"{safe_title}_zh.txt")
            with open(translate_file, "w", encoding="utf-8") as f:
                f.write(f"# {title}（中文翻译）\n\n{translated}")
            print(f"中文翻译已保存: {translate_file}")
            results["translation"] = translate_file
            # 后续分析用中文版本
            transcript = translated
    else:
        print("\n⏭️  步骤 3/4: 跳过翻译")

    # ── 步骤 4: 投研分析 ──
    if not skip_analyze:
        print("\n" + "=" * 60)
        print("🔍 步骤 4/4: 五维投研分析")
        print("=" * 60)

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("⚠️  未设置 ANTHROPIC_API_KEY，跳过分析")
            print("   逐字稿已保存，可手动粘贴给 Claude 分析")
        else:
            analysis = analyze_transcript(transcript, title, api_key)
            analysis_file = os.path.join(output_dir, f"{safe_title}_analysis.txt")
            with open(analysis_file, "w", encoding="utf-8") as f:
                f.write(f"# 投研分析：{title}\n\n{analysis}")
            print(f"投研分析已保存: {analysis_file}")
            results["analysis"] = analysis_file
    else:
        print("\n⏭️  步骤 4/4: 跳过分析")

    # ── 完成 ──
    print("\n" + "=" * 60)
    print("✅ 全流程完成!")
    print("=" * 60)
    print(f"\n📁 输出目录: {output_dir}")
    for key, path in results.items():
        if key == "title":
            continue
        label = {"transcript": "逐字稿", "translation": "中文翻译", "analysis": "投研分析"}.get(key, key)
        print(f"  {label}: {path}")

    return results


def run_daily_briefing(
    config: str = "podcasts.yaml",
    days: int = 1,
    category: str | None = None,
    output_dir: str = "output",
) -> str:
    """生成每日播客投研简报"""
    podcasts = load_podcasts(config)
    print(f"已加载 {len(podcasts)} 个播客，检查最近 {days} 天更新...\n")

    results = check_feeds(podcasts, days=days, category=category)
    output = format_episode_list(results)

    date_str = datetime.now().strftime("%Y-%m-%d")
    header = f"# 播客投研日报 ({date_str})\n\n共 {len(results)} 集新节目\n"
    full_output = header + output

    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"daily_{date_str}.md")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(full_output)

    print(f"\n日报已保存: {output_file}")

    # 打印摘要
    print(f"\n共 {len(results)} 集新节目:")
    for r in results[:10]:
        ep = r["episode"]
        print(f"  [{r['podcast_name']}] {ep['title']}")
    if len(results) > 10:
        print(f"  ... 还有 {len(results) - 10} 集")

    return output_file


def _safe_filename(title: str) -> str:
    """将标题转换为安全的文件名"""
    import re
    safe = re.sub(r'[\\/:*?"<>|]', '', title)
    safe = safe.replace(" ", "_")
    if len(safe) > 80:
        safe = safe[:80]
    return safe or "podcast"


def main():
    parser = argparse.ArgumentParser(
        description="播客投研系统 - 全流程管道",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── daily: 每日简报 ──
    daily_parser = subparsers.add_parser("daily", help="生成每日播客更新简报")
    daily_parser.add_argument("--days", type=int, default=1, help="检查最近 N 天（默认: 1）")
    daily_parser.add_argument("--category", choices=["investment", "tech", "macro", "crypto"])
    daily_parser.add_argument("--config", default="podcasts.yaml")
    daily_parser.add_argument("--output-dir", default="output")

    # ── run: 单集完整分析 ──
    run_parser = subparsers.add_parser("run", help="对单集播客执行完整投研分析")
    run_parser.add_argument("url", help="播客音频链接")
    run_parser.add_argument("--model", default="medium", choices=["tiny", "base", "small", "medium", "large"])
    run_parser.add_argument("--language", help="音频语言（如 en/zh）")
    run_parser.add_argument("--diarize", action="store_true", default=True, help="说话人分离（默认启用）")
    run_parser.add_argument("--no-diarize", action="store_true", help="禁用说话人分离")
    run_parser.add_argument("--hf-token", help="HuggingFace token")
    run_parser.add_argument("--num-speakers", type=int, help="说话人数量")
    run_parser.add_argument("--skip-translate", action="store_true", help="跳过翻译步骤")
    run_parser.add_argument("--skip-analyze", action="store_true", help="跳过分析步骤")
    run_parser.add_argument("--output-dir", default="output")

    # ── transcribe-only: 仅转录 ──
    tx_parser = subparsers.add_parser("transcribe", help="仅转录（不翻译、不分析）")
    tx_parser.add_argument("url", help="播客音频链接")
    tx_parser.add_argument("--model", default="medium", choices=["tiny", "base", "small", "medium", "large"])
    tx_parser.add_argument("--language", help="音频语言")
    tx_parser.add_argument("--diarize", action="store_true", default=True)
    tx_parser.add_argument("--no-diarize", action="store_true")
    tx_parser.add_argument("--hf-token", help="HuggingFace token")
    tx_parser.add_argument("--num-speakers", type=int)
    tx_parser.add_argument("--output-dir", default="output")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "daily":
        run_daily_briefing(
            config=args.config, days=args.days,
            category=args.category, output_dir=args.output_dir,
        )

    elif args.command == "run":
        diarize = not args.no_diarize
        run_pipeline(
            url=args.url, output_dir=args.output_dir,
            whisper_model=args.model, language=args.language,
            diarize=diarize, hf_token=args.hf_token,
            num_speakers=args.num_speakers,
            skip_translate=args.skip_translate,
            skip_analyze=args.skip_analyze,
        )

    elif args.command == "transcribe":
        diarize = not args.no_diarize
        run_pipeline(
            url=args.url, output_dir=args.output_dir,
            whisper_model=args.model, language=args.language,
            diarize=diarize, hf_token=args.hf_token,
            num_speakers=args.num_speakers,
            skip_translate=True, skip_analyze=True,
        )


if __name__ == "__main__":
    main()
