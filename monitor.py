#!/usr/bin/env python3
"""播客投研系统 - 节目监控

检查关注播客的 RSS Feed，输出最近更新的节目清单。
"""

import argparse
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import yaml


def load_podcasts(config_path: str = "podcasts.yaml") -> list[dict]:
    """加载播客配置"""
    path = Path(config_path)
    if not path.exists():
        print(f"错误: 配置文件 {config_path} 不存在", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("podcasts", [])


def fetch_rss(url: str) -> str:
    """获取 RSS Feed 内容"""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "PodcastResearchBot/1.0")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_episodes(xml: str, max_items: int = 5) -> list[dict]:
    """从 RSS XML 中提取最近的节目列表"""
    episodes = []
    items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)

    for item in items[:max_items]:
        title = _extract_tag(item, "title")
        pub_date_str = _extract_tag(item, "pubDate")
        link = _extract_tag(item, "link")
        duration = _extract_tag(item, "itunes:duration")
        description = _extract_tag(item, "itunes:summary") or _extract_tag(item, "description")

        # 提取音频 URL
        enclosure_m = re.search(r'<enclosure[^>]+url="([^"]+)"', item)
        audio_url = enclosure_m.group(1) if enclosure_m else None

        # 解析发布时间
        pub_date = None
        if pub_date_str:
            try:
                pub_date = parsedate_to_datetime(pub_date_str)
            except (ValueError, TypeError):
                pass

        if description:
            # 去掉 HTML 标签，截取前 200 字符
            description = re.sub(r"<[^>]+>", "", description).strip()
            description = re.sub(r"\s+", " ", description)
            if len(description) > 200:
                description = description[:200] + "..."

        episodes.append({
            "title": title or "未知标题",
            "pub_date": pub_date,
            "link": link,
            "audio_url": audio_url,
            "duration": duration,
            "description": description,
        })

    return episodes


def _extract_tag(xml: str, tag: str) -> str | None:
    """提取 XML 标签内容，支持 CDATA"""
    m = re.search(
        rf"<{re.escape(tag)}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{re.escape(tag)}>",
        xml, re.DOTALL,
    )
    return m.group(1).strip() if m else None


def check_feeds(
    podcasts: list[dict], days: int = 1, category: str | None = None,
) -> list[dict]:
    """检查所有播客 Feed，返回指定天数内更新的节目

    返回 [{"podcast": ..., "episode": ...}, ...]
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results = []

    for podcast in podcasts:
        if category and podcast.get("category") != category:
            continue

        name = podcast["name"]
        rss_url = podcast.get("rss_url")
        if not rss_url:
            continue

        print(f"  检查: {name}...", end=" ", flush=True)
        try:
            xml = fetch_rss(rss_url)
            episodes = parse_episodes(xml)

            new_count = 0
            for ep in episodes:
                if ep["pub_date"] and ep["pub_date"] >= cutoff:
                    results.append({
                        "podcast_name": name,
                        "category": podcast.get("category", ""),
                        "episode": ep,
                    })
                    new_count += 1

            if new_count > 0:
                print(f"✓ {new_count} 集新节目")
            else:
                print("无更新")

        except (urllib.error.URLError, TimeoutError) as e:
            print(f"✗ 请求失败: {e}")

    # 按发布时间倒序
    results.sort(key=lambda x: x["episode"]["pub_date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return results


def format_episode_list(results: list[dict]) -> str:
    """将节目列表格式化为可读文本"""
    if not results:
        return "暂无新节目更新。"

    lines = []
    current_category = None
    category_names = {
        "investment": "💰 投资",
        "tech": "🔬 科技",
        "macro": "📊 宏观经济",
        "crypto": "🪙 加密货币",
    }

    # 按 category 分组
    by_category: dict[str, list] = {}
    for r in results:
        cat = r["category"] or "other"
        by_category.setdefault(cat, []).append(r)

    for cat in ["investment", "macro", "tech", "crypto", "other"]:
        if cat not in by_category:
            continue
        cat_label = category_names.get(cat, cat)
        lines.append(f"\n## {cat_label}\n")

        for r in by_category[cat]:
            ep = r["episode"]
            podcast = r["podcast_name"]
            title = ep["title"]
            date_str = ep["pub_date"].strftime("%m-%d") if ep["pub_date"] else "未知"
            duration = f" ({ep['duration']})" if ep.get("duration") else ""

            lines.append(f"- **[{date_str}] {podcast}**{duration}")
            lines.append(f"  {title}")
            if ep.get("audio_url"):
                lines.append(f"  🔗 {ep['audio_url']}")
            elif ep.get("link"):
                lines.append(f"  🔗 {ep['link']}")
            if ep.get("description"):
                lines.append(f"  > {ep['description']}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="播客投研系统 - 检查关注播客的最新节目"
    )
    parser.add_argument(
        "--days", type=int, default=1,
        help="检查最近 N 天的更新（默认: 1）",
    )
    parser.add_argument(
        "--category", choices=["investment", "tech", "macro", "crypto"],
        help="只检查指定分类",
    )
    parser.add_argument(
        "--config", default="podcasts.yaml",
        help="播客配置文件路径（默认: podcasts.yaml）",
    )
    parser.add_argument(
        "-o", "--output", help="输出到文件",
    )

    args = parser.parse_args()

    podcasts = load_podcasts(args.config)
    print(f"已加载 {len(podcasts)} 个播客，检查最近 {args.days} 天更新...\n")

    results = check_feeds(podcasts, days=args.days, category=args.category)
    output = format_episode_list(results)

    header = f"# 播客投研日报 ({datetime.now().strftime('%Y-%m-%d')})\n"
    header += f"共 {len(results)} 集新节目\n"
    full_output = header + output

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(full_output)
        print(f"\n清单已保存到: {args.output}")
    else:
        print("\n" + "=" * 60)
        print(full_output)
        print("=" * 60)


if __name__ == "__main__":
    main()
