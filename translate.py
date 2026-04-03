#!/usr/bin/env python3
"""播客投研系统 - 逐字稿翻译

将英文播客逐字稿翻译为中文，保留说话人标签和结构。
"""

import argparse
import os
import sys
import time

import anthropic


TRANSLATE_SYSTEM_PROMPT = """\
你是专业的播客翻译员，精通金融投资和科技领域术语。

## 任务
将英文播客逐字稿翻译为中文。

## 要求
1. **保留说话人标签**：如 **说话人1**：保持不变，只翻译发言内容
2. **保留时间戳**：如 [00:05:32] 保持不变
3. **专业术语处理**：
   - 首次出现的专业术语标注英文原文，如「量化宽松（Quantitative Easing）」
   - 公司名、人名、产品名保留英文，如 NVIDIA、Jensen Huang、ChatGPT
   - 金融术语使用标准中文译法：P/E ratio → 市盈率，yield curve → 收益率曲线
4. **口语化翻译**：这是播客对话，翻译要自然口语化，不要书面体
5. **不要遗漏任何内容**，不要添加原文没有的内容
6. **直接输出翻译结果**，不要加任何前言或说明\
"""


def translate_transcript(transcript: str, api_key: str | None = None) -> str:
    """将英文逐字稿翻译为中文

    对于长文本自动分段翻译后拼接。
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("错误: 需要设置 ANTHROPIC_API_KEY 环境变量", file=sys.stderr)
        print("  export ANTHROPIC_API_KEY='your-api-key'", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # 按段落分割，分成若干块
    paragraphs = transcript.split("\n\n")
    chunks = _split_into_chunks(paragraphs, max_chars=8000)

    print(f"正在翻译（共 {len(chunks)} 段）...")
    start = time.time()

    translated_parts = []
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            print(f"  翻译第 {i + 1}/{len(chunks)} 段...")

        chunk_text = "\n\n".join(chunk)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16000,
            system=TRANSLATE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"请翻译以下播客逐字稿：\n\n{chunk_text}"}],
        )

        translated_parts.append(message.content[0].text)

    elapsed = time.time() - start
    print(f"翻译完成 ({elapsed:.1f}s)")

    return "\n\n".join(translated_parts)


def _split_into_chunks(paragraphs: list[str], max_chars: int) -> list[list[str]]:
    """将段落列表按字符数分块"""
    chunks = []
    current_chunk = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)
        if current_size + para_size > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(para)
        current_size += para_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [paragraphs]


def main():
    parser = argparse.ArgumentParser(
        description="播客投研系统 - 将英文逐字稿翻译为中文"
    )
    parser.add_argument("input", help="输入的英文逐字稿文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径（默认打印到终端）")

    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        transcript = f.read()

    translated = translate_transcript(transcript)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(translated)
        print(f"\n翻译已保存到: {args.output}")
    else:
        print("\n" + "=" * 60)
        print(translated)
        print("=" * 60)


if __name__ == "__main__":
    main()
