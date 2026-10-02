"""起重机械状态流转与台账口径的回归测试：只依赖标准库，python3 -m unittest 即可运行。

覆盖：
- 状态只能沿 正常 → 超载运行 → 检验中 → 已停用 单步前进，不能回退、不能跳步；
- 已停用不能再被安排检验，恢复使用必须先补齐上次年检；
- 缺年检日期时动作被拦下并说明缺的是「上次年检」；
- 额定起重量改小后列表按新值重排，重复读取顺序稳定；
- 台账与详情字段口径一致（工作级别不丢、起重机状态跟随内部 status）。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.crane import ACTION_RULES, RESTORE_ACTION, STATUS_ORDER, CraneService  # noqa: E402
from app.store import store  # noqa: E402


class CraneServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        store.__init__()  # 每个用例都从种子数据重新开始，避免共享内存状态
        self.service = CraneService()

    def test_list_sorted_by_capacity_desc(self) -> None:
        items, _ = self.service.list_entries()
        capacities = [float(str(item["额定起重量"]).rstrip("t")) for item in items]
        self.assertEqual(capacities, sorted(capacities, reverse=True))

    def test_rated_capacity_change_reorders_list_and_stays(self) -> None:
        entry, message = self.service.run_action(1, "降载运行", {"额定起重量": "5t"})
        self.assertIsNotNone(entry)
        self.assertEqual(entry["额定起重量"], "5t")
        first_read = [item["id"] for item in self.service.list_entries()[0]]
        # 模拟重新进入页面：再次读取，顺序不得跳回旧顺序。
        second_read = [item["id"] for item in self.service.list_entries()[0]]
        self.assertEqual(first_read, second_read)
        self.assertEqual(second_read[-1], 1)

    def test_statuses_progress_one_step_at_a_time(self) -> None:
        # 正常直接安排检验：跳步拦截。
        entry, message = self.service.run_action(1, "安排检验")
        self.assertIsNone(entry)
        self.assertIn("正常", message)
        # 超载再降载：回退拦截（超载与检验之间不能横跳回旧状态）。
        entry, _ = self.service.run_action(2, "降载运行")
        self.assertIsNone(entry)
        # 正常链路：超载运行 -> 检验中 -> 已停用 逐步放行。
        self.assertTrue(self.service.run_action(1, "降载运行")[0] is not None)
        self.assertEqual(self.service.run_action(1, "安排检验")[1], "起重机已安排检验")
        self.assertEqual(self.service.run_action(1, "办理停用")[1], "起重机已办理停用")
        self.assertEqual(self.service.get_entry(1)["status"], STATUS_ORDER[-1])

    def test_stopped_cannot_be_inspected(self) -> None:
        self.service.run_action(1, "降载运行")
        self.service.run_action(1, "安排检验")
        self.service.run_action(1, "办理停用")
        entry, message = self.service.run_action(1, "安排检验")
        self.assertIsNone(entry)
        self.assertIn("已停用", message)
        # 同样不能再降载、再停用。
        self.assertIsNone(self.service.run_action(1, "降载运行")[0])
        self.assertIsNone(self.service.run_action(1, "办理停用")[0])

    def test_restore_requires_inspection_date(self) -> None:
        # 种子 id=4 是缺「上次年检」的已停用记录。
        self.assertEqual(self.service.get_entry(4)["缺失字段"], ["上次年检"])
        entry, message = self.service.run_action(4, RESTORE_ACTION)
        self.assertIsNone(entry)
        self.assertIn("缺少必填字段：上次年检", message)
        # 非停用状态不允许恢复。
        self.assertIsNone(self.service.run_action(2, RESTORE_ACTION)[0])
        # 补齐年检后恢复为正常。
        entry, message = self.service.run_action(4, RESTORE_ACTION, {"上次年检": "2026-09-30"})
        self.assertIsNotNone(entry)
        self.assertEqual(entry["status"], "正常")
        self.assertEqual(entry["上次年检"], "2026-09-30")

    def test_inspection_required_before_inspection_and_stop(self) -> None:
        entry, _ = self.service.create_entry(
            {"起重机编号": "CRAN-T1", "起重机类型": "桥式", "额定起重量": "3t"}
        )
        new_id = entry["id"]
        self.service.run_action(new_id, "降载运行")
        _, message = self.service.run_action(new_id, "安排检验")
        self.assertIn("缺少必填字段：上次年检", message)
        self.assertIn("上次年检", self.service.get_entry(new_id)["缺年检提示"])

    def test_detail_and_list_share_fields(self) -> None:
        entry, _ = self.service.create_entry(
            {
                "起重机编号": "CRAN-T2",
                "起重机类型": "门式",
                "额定起重量": "8t",
                "跨度": "20m",
                "工作级别": "A5",
                "上次年检": "2026-05-01",
            }
        )
        new_id = entry["id"]
        detail = self.service.get_entry(new_id)
        listed = next(item for item in self.service.list_entries(size=1000)[0] if item["id"] == new_id)
        # 工作级别等扩展字段不再被登记逻辑丢掉。
        self.assertEqual(detail["工作级别"], "A5")
        self.assertEqual(listed["工作级别"], "A5")
        # 台账列「起重机状态」与内部 status 必须对得上。
        self.assertEqual(detail["起重机状态"], detail["status"])
        self.assertEqual(listed["起重机状态"], listed["status"])

    def test_action_rules_match_status_order(self) -> None:
        # 三个前进动作恰好对应状态序列的后三档。
        self.assertEqual([ACTION_RULES[a] for a in ("降载运行", "安排检验", "办理停用")], STATUS_ORDER[1:])


if __name__ == "__main__":
    unittest.main()
