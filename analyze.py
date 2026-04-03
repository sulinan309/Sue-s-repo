#!/usr/bin/env python3
"""播客投研系统 - 投研分析

对播客逐字稿进行五维投研分析，提取可操作的投资洞察。
"""

import argparse
import os
import sys
import time

import anthropic


ANALYZE_SYSTEM_PROMPT = """\
你是一位资深投资研究分析师，服务于一家顶级对冲基金。你的读者是基金经理，
他们需要从播客对话中提取可操作的投资洞察。

## 分析框架

对播客内容进行以下五个维度的深度分析：

### 1. 核心结论（他们在押什么）
- 嘉宾/主持人明确表达的投资观点和方向性判断
- 提到的具体标的（股票、行业、资产类别）
- 看多/看空的明确立场
- 时间框架（短期交易 vs 长期持有）

### 2. 关键论据（为什么）
- 支撑核心结论的数据、事实和逻辑链条
- 引用的信息源和数据点
- 类比和历史参照
- 他们认为市场定价错误的地方

### 3. 隐含假设（最重要）
- 他们没有明说但观点成立必须依赖的前提条件
- 对宏观环境的隐含假设（利率走向、经济周期、政策方向）
- 对竞争格局的隐含假设
- 对技术趋势延续性的假设
- 对管理层执行力的假设

### 4. 反证条件（如果错，会错在哪）
- 什么情况发生会使他们的核心结论失效
- 最大的下行风险是什么
- 历史上类似判断失误的案例
- 哪些信号出现意味着该撤退

### 5. 未被讨论的关键问题（他们没有说但你该问的）
- 对话中明显回避或遗漏的话题
- 缺失的反方观点
- 应该追问但没有追问的关键问题
- 与当前市场环境相关但被忽略的风险因素

## 输出要求

- 每个维度用清晰的标题和要点列表
- 涉及具体数字、标的、人名时必须准确引用原文
- 用中文输出（专业术语首次出现时标注英文）
- 在最后附上一段 50 字以内的"一句话总结"，概括这期播客最值得关注的一个点
- 直接输出分析结果，不要加开场白\
"""


def analyze_transcript(transcript: str, title: str, api_key: str | None = None) -> str:
    """对播客逐字稿进行五维投研分析"""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("错误: 需要设置 ANTHROPIC_API_KEY 环境变量", file=sys.stderr)
        print("  export ANTHROPIC_API_KEY='your-api-key'", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("正在进行投研分析...")
    start = time.time()

    # 如果逐字稿太长，截取前后部分（中间部分通常信息密度较低）
    max_chars = 100000
    if len(transcript) > max_chars:
        half = max_chars // 2
        transcript = (
            transcript[:half]
            + "\n\n[...中间部分省略...]\n\n"
            + transcript[-half:]
        )
        print(f"  逐字稿较长，已截取前后各 {half // 1000}K 字符")

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        system=ANALYZE_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"请对以下播客进行五维投研分析。\n\n播客标题：{title}\n\n逐字稿内容：\n{transcript}",
        }],
    )

    elapsed = time.time() - start
    print(f"分析完成 ({elapsed:.1f}s)")

    return message.content[0].text


def main():
    parser = argparse.ArgumentParser(
        description="播客投研系统 - 五维投研分析"
    )
    parser.add_argument("input", help="输入的逐字稿文件路径（中文或英文均可）")
    parser.add_argument("-o", "--output", help="输出文件路径（默认打印到终端）")
    parser.add_argument("--title", default="", help="播客标题（可选，辅助分析）")

    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        transcript = f.read()

    # 尝试从文件内容提取标题（第一行 # 开头的）
    title = args.title
    if not title:
        first_line = transcript.split("\n")[0]
        if first_line.startswith("# "):
            title = first_line[2:].strip()

    analysis = analyze_transcript(transcript, title)

    header = f"# 投研分析：{title}\n\n" if title else ""
    full_output = header + analysis

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(full_output)
        print(f"\n分析报告已保存到: {args.output}")
    else:
        print("\n" + "=" * 60)
        print(full_output)
        print("=" * 60)


if __name__ == "__main__":
    main()
