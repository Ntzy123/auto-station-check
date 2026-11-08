# test_core.py - StationCheckAutomation 单元测试

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from unittest.mock import patch, MagicMock

import pytest
from selenium.common.exceptions import TimeoutException

import auto_station_check.core
from auto_station_check.core import StationCheckAutomation


class TestBasics:
    """初始化与常量"""

    def test_init(self):
        automation = StationCheckAutomation()
        assert automation.driver is None
        assert automation.reason == "处理其他工作来不及答题"

    def test_selectors(self):
        automation = StationCheckAutomation()
        assert automation._SEL_TAB == ".adm-tabs-tab"
        assert automation._SEL_CARD == ".adm-pull-to-refresh-content > .bg-white.rounded"
        assert "岗位情况反馈" in automation._XPATH_FEEDBACK_BTN
        assert automation._SEL_POPUP == ".adm-popup"
        assert "确认" in automation._XPATH_CONFIRM

    def test_safe_quit_noop_when_none(self):
        StationCheckAutomation()._safe_quit_driver()


class TestWaitHelpers:

    @patch("auto_station_check.core.WebDriverWait")
    def test_wait_click_success(self, mock_wait):
        element = MagicMock()
        mock_wait.return_value.until.return_value = element

        automation = StationCheckAutomation()
        automation.driver = MagicMock()
        assert automation._wait_click("css", "div.test", wait_ms=1000) is True
        element.click.assert_called_once()

    @patch("auto_station_check.core.WebDriverWait")
    def test_wait_click_timeout(self, mock_wait):
        mock_wait.return_value.until.side_effect = TimeoutException()

        automation = StationCheckAutomation()
        automation.driver = MagicMock()
        assert automation._wait_click("css", "div.test", wait_ms=1000) is False

    @patch("auto_station_check.core.WebDriverWait")
    def test_wait_present(self, mock_wait):
        mock_wait.return_value.until.return_value = MagicMock()
        automation = StationCheckAutomation()
        automation.driver = MagicMock()
        assert automation._wait_present("css", "div.test", timeout_ms=1000) is True


class TestClickCards:

    def test_no_card(self):
        automation = StationCheckAutomation()
        automation.driver = MagicMock()
        automation.driver.find_elements.return_value = []
        assert automation._click_cards(0) is False

    def test_click_first_card(self):
        card = MagicMock()
        automation = StationCheckAutomation()
        automation.driver = MagicMock()
        automation.driver.find_elements.return_value = [card]
        assert automation._click_cards(0) is True
        card.click.assert_called_once()


class TestStep6Confirm:

    def test_confirm_success_logs_and_counts(self):
        automation = StationCheckAutomation()
        automation.driver = MagicMock()
        with (
            patch.object(automation, "_wait_click", return_value=True) as click,
            patch("auto_station_check.core._log_success") as success,
        ):
            assert automation._step_6_confirm() is True

        click.assert_called_once()
        success.assert_called_once()
        automation._log.info.assert_any_call("检查成功")

    def test_confirm_failure_no_success_log(self):
        automation = StationCheckAutomation()
        automation.driver = MagicMock()
        with (
            patch.object(automation, "_wait_click", return_value=False),
            patch("auto_station_check.core._log_success") as success,
        ):
            assert automation._step_6_confirm() is False

        success.assert_not_called()


class TestInjectToken:

    def test_cookie_written_with_fetched_token(self):
        automation = StationCheckAutomation()
        automation.driver = MagicMock()
        with patch(
            "auto_station_check.core.get_access_token", return_value="jwt-abc"
        ) as fetch:
            automation._inject_token()

        fetch.assert_called_once_with(
            auto_station_check.core.MOBILE, auto_station_check.core.PASSWORD
        )
        automation.driver.add_cookie.assert_called_once_with(
            {"name": "access_token_easycheck", "value": "jwt-abc", "path": "/"}
        )


class TestGetAccessToken:

    def test_returns_token(self):
        resp = MagicMock()
        resp.json.return_value = {"code": 0, "access_token": "jwt-abc"}
        with patch(
            "auto_station_check.core.requests.post", return_value=resp
        ) as post:
            assert auto_station_check.core.get_access_token("m", "p") == "jwt-abc"

        post.assert_called_once_with(
            auto_station_check.core.TOKEN_API,
            json={"mobile": "m", "password": "p"},
            timeout=30,
        )

    def test_missing_token_raises_after_retries(self):
        resp = MagicMock()
        resp.json.return_value = {"code": 2, "msg": "获取失败: 'location'"}
        with patch(
            "auto_station_check.core.requests.post", return_value=resp
        ) as post:
            with pytest.raises(RuntimeError):
                auto_station_check.core.get_access_token("m", "p", retries=3, interval=0)

        assert post.call_count == 3

    def test_retries_until_token(self):
        """接口阵发失败：第一次返回错误，第二次成功"""
        bad = MagicMock()
        bad.json.return_value = {"code": 2, "msg": "获取失败: 'location'"}
        good = MagicMock()
        good.json.return_value = {"access_token": "jwt-abc"}

        with patch(
            "auto_station_check.core.requests.post", side_effect=[bad, good]
        ) as post:
            token = auto_station_check.core.get_access_token("m", "p", interval=0)

        assert token == "jwt-abc"
        assert post.call_count == 2


class TestRunCycle:
    """流程编排：一轮把列表内待检查项处理完"""

    def test_no_item_ends_cycle(self):
        automation = StationCheckAutomation()
        with (
            patch.object(automation, "_step_1_open_list", return_value=True) as s1,
            patch.object(automation, "_step_2_find_item", return_value=False) as s2,
            patch.object(automation, "_step_3_open_detail") as s3,
            patch.object(automation, "_step_4_click_feedback") as s4,
            patch.object(automation, "_step_5_select_reason") as s5,
            patch.object(automation, "_step_6_confirm") as s6,
        ):
            automation.run_cycle()

        s1.assert_called_once()
        s2.assert_called_once()
        s3.assert_not_called()
        s4.assert_not_called()
        s5.assert_not_called()
        s6.assert_not_called()

    def test_item_with_confirm_enabled_loops_until_empty(self):
        """确认启用时：处理完一条继续下一条，列表空后结束"""
        automation = StationCheckAutomation()
        with (
            patch.object(automation, "_step_1_open_list", return_value=True) as s1,
            patch.object(automation, "_step_2_find_item", side_effect=[True, True, False]),
            patch.object(automation, "_step_3_open_detail", return_value=True),
            patch.object(automation, "_step_4_click_feedback", return_value=True),
            patch.object(automation, "_step_5_select_reason", return_value=True),
            patch.object(automation, "_step_6_confirm", return_value=True),
        ):
            automation.run_cycle()

        assert s1.call_count == 3

    def test_confirm_failure_stops_after_one(self):
        """确认失败时：条目不会消失，结束本轮避免重复点同一项"""
        automation = StationCheckAutomation()
        with (
            patch.object(automation, "_step_1_open_list", return_value=True) as s1,
            patch.object(automation, "_step_2_find_item", return_value=True) as s2,
            patch.object(automation, "_step_3_open_detail", return_value=True),
            patch.object(automation, "_step_4_click_feedback", return_value=True),
            patch.object(automation, "_step_5_select_reason", return_value=True) as s5,
            patch.object(automation, "_step_6_confirm", return_value=False) as s6,
        ):
            automation.run_cycle()

        s1.assert_called_once()
        s2.assert_called_once()
        s5.assert_called_once()
        s6.assert_called_once()

    def test_open_list_failure_aborts(self):
        automation = StationCheckAutomation()
        with (
            patch.object(automation, "_step_1_open_list", return_value=False) as s1,
            patch.object(automation, "_step_2_find_item") as s2,
        ):
            automation.run_cycle()

        s1.assert_called_once()
        s2.assert_not_called()

    def test_detail_failure_aborts(self):
        automation = StationCheckAutomation()
        with (
            patch.object(automation, "_step_1_open_list", return_value=True),
            patch.object(automation, "_step_2_find_item", return_value=True),
            patch.object(automation, "_step_3_open_detail", return_value=False),
            patch.object(automation, "_step_4_click_feedback") as s4,
            patch.object(automation, "_step_6_confirm") as s6,
        ):
            automation.run_cycle()

        s4.assert_not_called()
        s6.assert_not_called()
