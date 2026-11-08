# setup_deps.py - 自动克隆缺失的依赖仓库

import os
import subprocess
import sys

REPOS = [
    ("easycheck_manager", "https://github.com/Ntzy123/easycheck_manager.git"),
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    for name, url in REPOS:
        target = os.path.join(BASE_DIR, "..", name)
        if os.path.isdir(target):
            print(f"  ✅ {name} 已存在，跳过克隆")
        else:
            print(f"  ⏳ 正在克隆 {name} ...")
            result = subprocess.run(
                ["git", "clone", url, target],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(f"  ❌ 克隆 {name} 失败: {result.stderr.strip()}")
                sys.exit(1)
            print(f"  ✅ {name} 克隆完成")


if __name__ == "__main__":
    main()
