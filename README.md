# auto_station_check - 岗位检查自动化工具

基于 Python + Edge WebDriver 的轻松夜答「岗位检查」自动化工具，每分钟轮询一次，7x24h 不间断运行。

---

## 自动化流程

1. 打开列表页 `https://rm.vankeservice.com/easycheck/#/postCheck/list`
2. 切一次「已检查 / 未检查」标签，触发数据刷新（首次进入列表是空态）
3. 检测待检查项（`.adm-pull-to-refresh-content > .bg-white.rounded`），无则本轮结束
4. 点击第一项进入「岗位检查详情」
5. 点击底部「岗位情况反馈」
6. 在弹层中选择「处理其他工作来不及答题」
7. 点击「确认」提交（提交成功后记入当日汇总日志）
8. 本轮结束，等待到下一分钟整再重复

> 单轮最多处理 `MAX_ITEMS_PER_CYCLE`（默认 20）项，剩余的下轮继续；提交失败会立即结束本轮，避免重复点同一项。

## 账号与 token

不使用配置文件，账号与选项文案硬编码在 `src/auto_station_check/core.py` 顶部：

```python
MOBILE = "18208475905"
PASSWORD = "H@ml000711"
REASON = "处理其他工作来不及答题"
TOKEN_API = "https://aec.kyrian.asia/api/get-access-token"
```

启动（及每次重建驱动）时 `POST TOKEN_API`，body `{"mobile","password"}`，取响应里的 `access_token` 写入 cookie `access_token_easycheck`，无需手动维护 JWT。

## 快速开始

```bash
make setup   # 创建 venv 并安装依赖（含同仓库的 easycheck_manager）
make run     # 运行
make test    # 测试
make build   # PyInstaller 打包
```

或直接：

```bash
python -m auto_station_check
```

## 恢复「确认」动作

编辑 `src/auto_station_check/core.py` 的 `_step_6_confirm()`，解开注释并删掉最后一行 `return False`。

## 项目结构

```
auto-station-check/
├── src/auto_station_check/
│   ├── __main__.py          # 入口（驱动自检 + 主循环）
│   ├── config_loader.py     # config.toml 读取
│   └── core.py              # 岗位检查流程
├── tests/
├── config.toml
├── Makefile
└── pyproject.toml
```
