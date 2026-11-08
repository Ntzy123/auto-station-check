# __main__.py - 程序入口

import sys

from easycheck_manager import WebDriverManager
from auto_station_check.core import StationCheckAutomation


def main():
    print("=" * 55)
    print("  EdgeDriver 环境检查")
    print("=" * 55)
    manager = WebDriverManager()
    manager.start()

    print("\n" + "=" * 55)
    print("  开始岗位检查自动化流程")
    print("=" * 55)
    automation = StationCheckAutomation()
    try:
        automation.run()
    except KeyboardInterrupt:
        print("\n  收到中断信号，正在退出...")
        automation.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
