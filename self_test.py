#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自检：用构造样本验证 repo_radar 的评分逻辑是否符合预期。"""

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"D:/Users/Lq/Documents/GitHub/gh-repo-radar")
from repo_radar import score_repo, grade  # noqa: E402

NOW = datetime.now(timezone.utc)


def mk(days_ago_push, stars=1000, lic="MIT", open_i=10,
       created_days_ago=1500, archived=False, forks=100):
    return {
        "stargazers_count": stars,
        "forks_count": forks,
        "open_issues_count": open_i,
        "license": {"spdx_id": lic},
        "pushed_at": (NOW - timedelta(days=days_ago_push)).isoformat(),
        "created_at": (NOW - timedelta(days=created_days_ago)).isoformat(),
        "archived": archived,
    }


CASES = [
    ("健康项目：昨天提交/30+贡献者/MIT/3年老项目",
     mk(1, stars=8000, lic="MIT", open_i=50), 30, "强烈推荐"),
    ("停滞项目：半年没提交/单人/新项目",
     mk(200, stars=500, lic="MIT", open_i=80, created_days_ago=100), 1, "不建议"),
    ("弃坑项目：两年无提交",
     mk(800, stars=3000, lic="MIT", open_i=400), 5, "不建议"),
    ("GPL 陷阱：活跃但许可证有传染性",
     mk(3, stars=2000, lic="GPL-3.0", open_i=100), 25, None),
    ("已归档仓库：即使 star 很高也应压到 15 分内",
     mk(2, stars=50000, lic="MIT", open_i=5, archived=True), 50, "不建议"),
    ("无许可证项目：商用有法律风险",
     mk(10, stars=1500, lic=None, open_i=30), 20, None),
    ("小型单人活跃项目：刚起步",
     mk(2, stars=80, lic="Apache-2.0", open_i=3, created_days_ago=200), 1, None),
]

print("=" * 78)
print("  评分逻辑自检")
print("=" * 78)
print()

fails = 0
for name, repo, contrib, expect_grade in CASES:
    r = score_repo(repo, contrib)
    g = grade(r["score"])
    ok = "OK " if (expect_grade is None or g == expect_grade) else "FAIL"
    if ok == "FAIL":
        fails += 1
    print(f"[{ok}] {name}")
    print(f"       分数={r['score']:>5}  评级={g}"
          + (f"   期望={expect_grade}" if expect_grade else ""))
    print(f"       加分: {r['reasons'][:3]}")
    if r["warnings"]:
        print(f"       警告: {r['warnings'][:2]}")
    print()

print("=" * 78)
print("  归档仓库强制压分检查 …", end=" ")
arch = score_repo(mk(2, stars=50000, archived=True), 50)
print(f"分数={arch['score']} {'通过' if arch['score'] <= 15 else '失败'}")
if arch["score"] > 15:
    fails += 1

print("  GPL 许可证降分检查 …", end=" ")
gpl = score_repo(mk(3, stars=2000, lic="GPL-3.0"), 25)
mit = score_repo(mk(3, stars=2000, lic="MIT"), 25)
print(f"GPL={gpl['score']} vs MIT={mit['score']} "
      f"{'通过' if gpl['score'] < mit['score'] else '失败'}")
if gpl["score"] >= mit["score"]:
    fails += 1

print("  弃坑项目低于健康项目 …", end=" ")
dead = score_repo(mk(800, stars=3000), 5)["score"]
alive = score_repo(mk(1, stars=3000), 5)["score"]
print(f"弃坑={dead} 健康={alive} {'通过' if dead < alive else '失败'}")
if dead >= alive:
    fails += 1

print()
print("=" * 78)
print(f"  结论：{'全部通过' if fails == 0 else f'{fails} 项失败'}")
print("=" * 78)
sys.exit(1 if fails else 0)
