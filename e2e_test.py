#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线端到端测试：monkeypatch 掉 HTTP 层，喂构造数据，验证完整流程与输出格式。"""

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"D:/Users/Lq/Documents/GitHub/gh-repo-radar")
import repo_radar as rr  # noqa: E402

NOW = datetime.now(timezone.utc)


def mk(fn, days_ago_push, stars, lic, open_i, contrib_days=1500, archived=False):
    return {
        "full_name": fn,
        "html_url": f"https://github.com/{fn}",
        "description": f"示例项目 {fn} —— 用于验证输出渲染是否正常",
        "stargazers_count": stars,
        "forks_count": stars // 10,
        "open_issues_count": open_i,
        "language": "Python",
        "license": {"spdx_id": lic} if lic else None,
        "pushed_at": (NOW - timedelta(days=days_ago_push)).isoformat(),
        "created_at": (NOW - timedelta(days=contrib_days)).isoformat(),
        "archived": archived,
    }


FAKE = {
    "acme/healthy-forecast": (mk("acme/healthy-forecast", 1, 12000, "Apache-2.0", 40), 45),
    "acme/mature-ts": (mk("acme/mature-ts", 20, 5400, "MIT", 120), 22),
    "old/dead-project": (mk("old/dead-project", 900, 8000, "MIT", 300), 12),
    "risky/gpl-tool": (mk("risky/gpl-tool", 5, 3100, "GPL-3.0", 90), 30),
    "small/solo-dev": (mk("small/solo-dev", 2, 140, "MIT", 4, contrib_days=200), 1),
    "legacy/archived": (mk("legacy/archived", 1, 20000, "MIT", 5, archived=True), 60),
    "legal/nolicense": (mk("legal/nolicense", 15, 900, None, 25), 15),
}

_call_count = {"search": 0}

def fake_search(query, token, per_page=30, language=None, licenses=None,
                min_stars=50, pushed_after=None):
    _call_count["search"] += 1
    return [{"full_name": fn, **rec[0]} for fn, rec in FAKE.items()]

def fake_contrib(full_name, token):
    return FAKE[full_name][1] if full_name in FAKE else None

rr.search_repos = fake_search
rr.get_contributor_count = fake_contrib

sys.argv = ["repo_radar.py", "-q", "predictive maintenance", "--top", "10"]
sys.stdout.reconfigure(encoding="utf-8")

print()
rc = rr.main()
print()
print("=" * 74)
print(f"  流程退出码: {rc}   (0 = 正常)")
print(f"  搜索调用次数: {_call_count['search']}")
print("=" * 74)
