"""起重机械业务规则：状态流转、字段校验与筛选口径都收在这里。

核心约束：
- 状态只能沿 正常 → 超载运行 → 检验中 → 已停用 单向推进，不允许回跳或横跳；
  唯一的例外是已停用后凭补齐的年检办理「恢复使用」，直接回到正常。
- 已停用的起重机不能再被安排检验。
- 恢复使用前必须先补齐「上次年检」日期，缺项要明确报出缺哪一项。
- 列表按当前额定起重量从大到小排序，起重量调整后顺序立即重排，
  排序在服务端完成，重新进入页面不会回到旧顺序。
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "crane"
REQUIRED_FIELDS = ["起重机编号", "起重机类型", "额定起重量"]
# 可在台账上维护的全部字段；创建/修改都只允许落这些键。
EDITABLE_FIELDS = [
    "起重机编号", "起重机类型", "额定起重量", "跨度", "工作级别",
    "操作人员", "上次年检",
]
STATUS_FIELD = "起重机状态"
ANNUAL_INSPECTION_FIELD = "上次年检"
STATUS_ORDER = ["正常", "超载运行", "检验中", "已停用"]
# 状态机的前向动作：动作只负责把记录推到「下一状态」。
ACTION_RULES = {"降载运行": "超载运行", "安排检验": "检验中", "办理停用": "已停用"}
# 从已停用恢复到正常的专用动作。
RESTORE_ACTION = "恢复使用"


def _capacity_key(row: dict[str, Any]) -> tuple[int, float, int]:
    """额定起重量排序键：提取数字部分，从大到小；解析不出的沉底，同值按编号升序。"""
    raw = str(row.get("额定起重量") or "")
    match = re.search(r"\d+(?:\.\d+)?", raw)
    value = float(match.group()) if match else float("-inf")
    # 第一项固定 1：配合 reverse=True 时正常数值恒排在 -inf 前面；
    # id 取负，使相同起重量仍按编号升序。
    return 1 if match else 0, value, -int(row.get("id", 0))


class CraneService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("起重机编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 服务端按当前额定起重量重排，保证任何入口拿到的顺序都一致。
        rows = sorted(rows, key=_capacity_key, reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def missing_fields(self, entry: dict[str, Any]) -> list[str]:
        """返回记录上仍缺、且会影响流转的字段（目前只有年检日期）。"""
        return [
            field for field in [ANNUAL_INSPECTION_FIELD]
            if not str(entry.get(field) or "").strip()
        ]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in EDITABLE_FIELDS:
            if str(values.get(field) or "").strip():
                entry[field] = values.get(field)
        self._apply_status(entry, STATUS_ORDER[0])
        rows.append(entry)
        return entry, []

    def update_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """修改台账字段（如调小额定起重量、补录年检日期）；空串视为清空，必填项不允许清空。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"起重机 {entry_id} 不存在或已归档"
        for field in EDITABLE_FIELDS:
            if field not in values:
                continue
            if field in REQUIRED_FIELDS and not str(values.get(field) or "").strip():
                return None, f"{field}为必填项，不能置空"
            entry[field] = values.get(field)
        return entry, "起重机台账已更新"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"起重机 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES and action != RESTORE_ACTION:
            return None, f"动作「{action}」不属于起重机械可执行范围"

        current = str(entry.get("status") or STATUS_ORDER[0])

        if action == RESTORE_ACTION:
            return self._restore(entry, current)

        target = ACTION_RULES[action]
        if current == STATUS_ORDER[-1]:
            return None, "起重机已停用，不能再安排检验或继续流转；如需启用请先补齐年检后办理恢复使用"
        try:
            current_index = STATUS_ORDER.index(current)
        except ValueError:
            current_index = -1
        target_index = STATUS_ORDER.index(target)
        if target_index != current_index + 1:
            return None, (
                f"状态必须按 正常 → 超载运行 → 检验中 → 已停用 顺序推进，"
                f"当前为「{current}」，不能直接执行「{action}」"
            )

        self._apply_status(entry, target)
        return entry, f"起重机已{action}"

    def _restore(self, entry: dict[str, Any], current: str) -> tuple[dict[str, Any], str] | tuple[None, str]:
        """已停用 → 正常：必须先补齐年检，且只有停用状态能恢复。"""
        if current != STATUS_ORDER[-1]:
            return None, f"只有已停用的起重机才能恢复使用，当前状态为「{current}」"
        missing = self.missing_fields(entry)
        if missing:
            return None, (
                f"无法恢复使用：缺少{'、'.join(missing)}，"
                f"请先补齐{ANNUAL_INSPECTION_FIELD}日期后再办理恢复使用"
            )
        self._apply_status(entry, STATUS_ORDER[0])
        return entry, "年检已补齐，起重机已恢复使用"

    def _apply_status(self, entry: dict[str, Any], status: str) -> None:
        """状态唯一落库口径：内部 status 与台账/详情展示用的中文字段同时更新。"""
        entry["status"] = status
        entry[STATUS_FIELD] = status
        entry["pending"] = status != STATUS_ORDER[-1]
        entry["abnormal"] = status == "超载运行"
