# core.py - 岗位检查自动化核心逻辑

import base64
import json
import logging
import os
import time
from datetime import datetime, timedelta

import requests
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ---------------------------------------------------------------------------
# 日志子系统
#   asc.log           —— 实时运行日志（所有操作），保留 48 小时
#   asc_YYYYMMDD.log  —— 每日检查成功汇总，日终自动追加统计行
# ---------------------------------------------------------------------------

LOG_DIR = "log"
LOG_FILE = os.path.join(LOG_DIR, "asc.log")
_logger = None
_daily_finalized_date = None  # 最后处理过的日期（YYYYMMDD）

BASE_URL = "https://rm.vankeservice.com/easycheck/"
# 岗位检查列表页（hash 路由，token 通过 cookie access_token_easycheck 注入）
LIST_URL = BASE_URL + "#/postCheck/list"

# easycheck 登录账号（换取 access_token_easycheck）
MOBILE = "18208475905"
PASSWORD = "H@ml000711"
# 在岗异常原因文案（必须与页面选项完全一致）
REASON = "处理其他工作来不及答题"
TOKEN_API = "https://aec.kyrian.asia/api/get-access-token"

# token 本地缓存（相对运行目录，与 log/ 同级）
CACHE_FILE = "cache"
# token 剩余有效期不足该秒数时重新获取（JWT 实测有效期 7 天）
REFRESH_AHEAD = 3600
# token 不是 JWT / 解不出 exp 时的兜底有效期
DEFAULT_TTL = 86400

# 单轮最多处理条数，防止页面异常时死循环
MAX_ITEMS_PER_CYCLE = 20


def _jwt_exp(token):
    """从 JWT payload 里取 exp（秒级时间戳），解不出返回 None。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return int(exp) if exp else None
    except Exception:
        return None


def _read_cache(mobile):
    """读本地缓存，返回仍可用的 token；缺失/损坏/临近过期/账号不符返回 None。"""
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        token = data.get("access_token")
        expires_at = int(data.get("expires_at") or 0)
        if data.get("mobile") == mobile and token and expires_at - time.time() > REFRESH_AHEAD:
            return token
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def _write_cache(token, mobile):
    """把 token 与获取/过期时间写入本地缓存。"""
    now = int(time.time())
    data = {
        "access_token": token,
        "obtained_at": now,
        "expires_at": _jwt_exp(token) or (now + DEFAULT_TTL),
        "mobile": mobile,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def get_access_token(mobile, password, retries=3, interval=3):
    """取 easycheck access_token_easycheck（JWT）：优先本地缓存，过期或临近过期才调接口。

    接口偶发 500（服务端上游 OAuth 步骤失败），重试几次即可。
    """
    cached = _read_cache(mobile)
    if cached:
        return cached

    err = ""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                TOKEN_API, json={"mobile": mobile, "password": password}, timeout=30
            )
            token = (resp.json() or {}).get("access_token")
            if token:
                _write_cache(token, mobile)
                return token
            err = f"HTTP {resp.status_code} {resp.text[:200]}"
        except requests.RequestException as e:
            err = repr(e)
        if attempt < retries:
            time.sleep(interval)
    raise RuntimeError(f"获取 access_token 失败（{retries} 次）: {err}")


def _get_logger():
    """获取 logger 实例，首次调用时初始化 asc.log。"""
    global _logger
    if _logger is None:
        _logger = logging.getLogger("asc")
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
        _ensure_log()
    return _logger


def _ensure_log():
    """确保日志目录存在、asc.log handler 已就绪。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    for h in _logger.handlers[:]:
        h.close()
        _logger.removeHandler(h)
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    _logger.addHandler(handler)


def _log_success():
    """将 '检查成功' 追加到当日汇总文件 asc_YYYYMMDD.log。"""
    log_file = os.path.join(LOG_DIR, f"asc_{datetime.now().strftime('%Y%m%d')}.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 检查成功\n")


def _daily_maintenance():
    """跨日维护：汇总前一日日志 + 清理 asc.log 旧条目。"""
    global _daily_finalized_date
    today = datetime.now().strftime("%Y%m%d")
    if today == _daily_finalized_date:
        return

    if _daily_finalized_date is not None:
        _finalize_prev_log(_daily_finalized_date)

    _daily_finalized_date = today
    _trim_old_entries()


def _finalize_prev_log(date_str):
    """在指定日期的汇总日志文件开头插入当日统计行。"""
    log_file = os.path.join(LOG_DIR, f"asc_{date_str}.log")
    if not os.path.exists(log_file):
        return
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    success_count = sum(1 for line in lines if "检查成功" in line)
    if success_count == 0:
        return

    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    summary = f"[{date_fmt}] 处理了 {success_count} 条岗位检查\n\n"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(summary)
        f.writelines(lines)


def _trim_old_entries():
    """删除 asc.log 中昨天以前（不含昨天）的日志条目。"""
    if not os.path.exists(LOG_FILE):
        return
    cutoff = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    kept = []
    in_range = False

    for line in lines:
        is_new_entry = (
            len(line) >= 10 and line[0:4].isdigit() and line[4] == "-"
        )
        if is_new_entry:
            in_range = line[:10] >= cutoff
        if in_range:
            kept.append(line)

    if len(kept) < len(lines):
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(kept)


# ---------------------------------------------------------------------------
# 核心自动化类
#
# 选择器来自真实页面结构（antd-mobile + tailwind），不使用绝对 XPath：
#   列表页      #root > nav / tabs / .adm-pull-to-refresh-content > 卡片
#   详情页      底部固定栏 <button><span>岗位情况反馈</span></button>
#   异常弹层    .adm-popup（body 末尾 portal）
# ---------------------------------------------------------------------------

class StationCheckAutomation:
    """岗位检查自动化流程"""

    _SEL_TAB = ".adm-tabs-tab"                                    # [0]=未检查 [1]=已检查
    _SEL_CARD = ".adm-pull-to-refresh-content > .bg-white.rounded"  # 待检查卡片
    _SEL_EMPTY = ".adm-pull-to-refresh-content .flex-center"        # 空态占位
    _XPATH_FEEDBACK_BTN = "//button[.//span[normalize-space()='岗位情况反馈']]"
    _SEL_POPUP = ".adm-popup"
    _XPATH_REASON = "//div[contains(@class,'adm-popup')]//div[normalize-space()='{reason}']"
    _XPATH_CONFIRM = "//div[contains(@class,'adm-popup')]//button[.//span[normalize-space()='确认']]"

    def __init__(self):
        self.driver = None
        self._log = _get_logger()
        self.reason = REASON
        self._token = None

    def _create_driver(self):
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--log-level=3")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        self.driver = webdriver.Edge(options=options)
        self.driver.set_page_load_timeout(40)

    # -- 基础工具 ---------------------------------------------------------

    def _wait_click(self, by, selector, wait_ms=5000, delay_ms=0):
        try:
            element = WebDriverWait(self.driver, wait_ms / 1000).until(
                EC.element_to_be_clickable((by, selector))
            )
            element.click()
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
            return True
        except (TimeoutException, WebDriverException):
            return False

    def _wait_present(self, by, selector, timeout_ms=5000):
        try:
            WebDriverWait(self.driver, timeout_ms / 1000).until(
                EC.presence_of_element_located((by, selector))
            )
            return True
        except (TimeoutException, WebDriverException):
            return False

    def _click_cards(self, index=0):
        """点击第 index 张卡片（卡片为可点击 div，用 JS 点击更稳）"""
        cards = self.driver.find_elements(By.CSS_SELECTOR, self._SEL_CARD)
        if len(cards) <= index:
            return False
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", cards[index]
            )
            cards[index].click()
        except WebDriverException:
            try:
                self.driver.execute_script("arguments[0].click();", cards[index])
            except WebDriverException:
                return False
        return True

    def _inject_token(self):
        """取 token（优先本地缓存），写入 cookie access_token_easycheck"""
        token = get_access_token(MOBILE, PASSWORD)
        self._token = token
        self.driver.get(BASE_URL)
        time.sleep(1)
        self.driver.add_cookie(
            {"name": "access_token_easycheck", "value": token, "path": "/"}
        )
        self._log.info("  已注入 access_token_easycheck")

    def _refresh_token(self):
        """每分钟调用一次：缓存里的 token 临近过期就换新，并更新浏览器 cookie。"""
        token = get_access_token(MOBILE, PASSWORD)
        if token == self._token:
            return
        self._token = token
        if self.driver is not None:
            self.driver.add_cookie(
                {"name": "access_token_easycheck", "value": token, "path": "/"}
            )
            self._log.info("  token 已续期，cookie 已更新")

    # -- 流程步骤 ---------------------------------------------------------

    def _step_1_open_list(self):
        """打开列表页并切一次标签，触发数据刷新（首次进入列表是空态）"""
        try:
            self.driver.get(LIST_URL)
        except WebDriverException as e:
            self._log.error("  [Step1] 打开列表页失败: %s", e)
            return False
        if not self._wait_present(By.CSS_SELECTOR, self._SEL_TAB, 15000):
            self._log.warning("  [Step1] 页面未加载出标签页（token 可能已失效）")
            return False

        tabs = self.driver.find_elements(By.CSS_SELECTOR, self._SEL_TAB)
        if len(tabs) < 2:
            self._log.warning("  [Step1] 未找到<未检查/已检查>标签")
            return False
        tabs[1].click()
        time.sleep(1)
        self.driver.find_elements(By.CSS_SELECTOR, self._SEL_TAB)[0].click()
        self._log.info("  [Step1] 列表页就绪")
        return True

    def _step_2_find_item(self, timeout_ms=8000):
        """等待列表加载完成，返回是否存在待检查项"""
        end = time.time() + timeout_ms / 1000
        while time.time() < end:
            if self.driver.find_elements(By.CSS_SELECTOR, self._SEL_CARD):
                self._log.info("  [Step2] 检测到待检查项")
                return True
            if self.driver.find_elements(By.CSS_SELECTOR, self._SEL_EMPTY):
                self._log.info("  [Step2] 暂无待检查项")
                return False
            time.sleep(0.3)
        self._log.warning("  [Step2] 列表加载超时")
        return False

    def _step_3_open_detail(self):
        if not self._click_cards(0):
            self._log.warning("  [Step3] 点击检查项失败")
            return False
        if not self._wait_present(By.XPATH, self._XPATH_FEEDBACK_BTN, 10000):
            self._log.warning("  [Step3] 详情页未加载出<岗位情况反馈>")
            return False
        self._log.info("  [Step3] 已进入岗位检查详情")
        return True

    def _step_4_click_feedback(self):
        ok = self._wait_click(By.XPATH, self._XPATH_FEEDBACK_BTN, 8000, 800)
        if ok:
            self._log.info("  [Step4] 点击<岗位情况反馈>成功")
        else:
            self._log.warning("  [Step4] 点击<岗位情况反馈>失败")
        return ok

    def _step_5_select_reason(self):
        if not self._wait_present(By.CSS_SELECTOR, self._SEL_POPUP, 5000):
            self._log.warning("  [Step5] 异常原因弹层未出现")
            return False
        ok = self._wait_click(By.XPATH, self._XPATH_REASON.format(reason=self.reason), 5000, 500)
        if ok:
            self._log.info("  [Step5] 选择原因<%s>成功", self.reason)
        else:
            self._log.warning("  [Step5] 选择原因<%s>失败", self.reason)
        return ok

    def _step_6_confirm(self):
        """提交确认，返回是否提交成功。"""
        ok = self._wait_click(By.XPATH, self._XPATH_CONFIRM, 5000, 1500)
        if ok:
            self._log.info("  [Step6] 点击<确认>成功")
            self._log.info("检查成功")
            _log_success()
        else:
            self._log.warning("  [Step6] 点击<确认>失败")
        return ok

    # -- 轮次编排 ---------------------------------------------------------

    def run_cycle(self):
        """执行一轮：把当前列表里的待检查项依次处理完（每项重新进入列表）"""
        handled = 0
        for _ in range(MAX_ITEMS_PER_CYCLE):
            if not self._step_1_open_list():
                return
            if not self._step_2_find_item():
                break
            if not self._step_3_open_detail():
                break
            if not self._step_4_click_feedback():
                break
            if not self._step_5_select_reason():
                break
            if not self._step_6_confirm():
                # 提交失败：条目不会消失，再循环只会重复同一项
                return
            handled += 1
        self._log.info("  [轮次] 本轮结束，共处理 %d 项", handled)

    def run(self):
        """主循环 - 每分钟一轮"""
        while True:
            _daily_maintenance()
            now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            print(f"\n[{now}] 运行中...")
            try:
                if self.driver is None:
                    self._create_driver()
                    self._inject_token()
                else:
                    self._refresh_token()
                self.run_cycle()
            except WebDriverException as e:
                print("  [主循环] WebDriver异常，正在重新创建驱动...")
                self._log.error("  [主循环] WebDriver异常: %s", e)
                self._safe_quit_driver()
                self.driver = None
            except Exception as e:
                # 取 token / 建驱动失败时一并重建，下一分钟自动恢复
                print("  [主循环] 未知异常，下一分钟重建驱动重试...")
                self._log.error("  [主循环] 未知异常: %s", e)
                self._safe_quit_driver()
                self.driver = None

            # 对齐到下一分钟
            time.sleep(60 - time.time() % 60)

    def _safe_quit_driver(self):
        if self.driver is None:
            return
        try:
            self.driver.quit()
        except Exception:
            pass

    def stop(self):
        """停止自动化流程"""
        if _daily_finalized_date is not None:
            _finalize_prev_log(_daily_finalized_date)
        self._safe_quit_driver()
