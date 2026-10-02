"""起重机械业务规则：状态流转、字段校验与筛选口径都收在这里。

状态只能沿 正常 → 超载运行 → 检验中 → 已停用 顺序单步前进，不允许跳步或回退；
已停用后唯一的出路是「恢复使用」，且必须先补齐上次年检，停用期间不能再安排检验。
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "crane"
# 登记时必须填写的字段；工作级别等其余字段允许后补，但都会原样落库。
REQUIRED_FIELDS = ["起重机编号", "起重机类型", "额定起重量"]
# 起重机台账的全部业务字段（「起重机状态」由内部 status 派生，不在可编辑字段里）。
BUSINESS_FIELDS = [
    "起重机编号", "起重机类型", "额定起重量", "跨度", "工作级别",
    "操作人员", "上次年检",
]
EDITABLE_FIELDS = ["额定起重量", "跨度", "工作级别", "操作人员", "上次年检"]
# 年检日期字段名：安排检验、办理停用、恢复使用之前都必须先有它。
INSPECTION_FIELD = "上次年检"

STATUS_ORDER = ["正常", "超载运行", "检验中", "已停用"]
# 每个动作把状态向前推进一步，是否允许执行还要看当前状态在序列里的位置。
ACTION_RULES = {"降载运行": "超载运行", "安排检验": "检验中", "办理停用": "已停用"}
RESTORE_ACTION = "恢复使用"
NEGATIVE_ACTIONS = ["降载运行"]

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _as_number(value: Any) -> float:
    """把「50」「50t」之类的额定起重量解析成数值，解析不出按 0 处理。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value))
    return float(match.group()) if match else 0.0


def _is_blank(value: Any) -> bool:
    return not str(value if value is not None else "").strip()


class CraneService:
    # ---- 读取 -----------------------------------------------------------
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
        # 台账统一按最新的额定起重量从大到小排，容量相同按登记先后；
        # 排序在后端完成，重新进入页面拿到的顺序不会再退回旧顺序。
        rows = sorted(rows, key=lambda row: (-_as_number(row.get("额定起重量")), int(row.get("id", 0))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._view(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._view(entry) if entry is not None else None

    def _missing_fields(self, entry: dict[str, Any]) -> list[str]:
        """年检日期缺失时明确指出缺哪一项，供列表、详情与动作拦截共用。"""
        return [INSPECTION_FIELD] if _is_blank(entry.get(INSPECTION_FIELD)) else []

    def _view(self, entry: dict[str, Any]) -> dict[str, Any]:
        """台账与详情共用同一份出参口径，保证工作级别、状态等字段对得上。"""
        view = dict(entry)
        for field in BUSINESS_FIELDS:
            view.setdefault(field, "")
        # 「起重机状态」始终跟随内部 status，杜绝两个状态字段各说各话。
        view["起重机状态"] = entry.get("status", STATUS_ORDER[0])
        missing = self._missing_fields(entry)
        view["缺失字段"] = missing
        view["缺年检提示"] = f"缺少必填字段：{INSPECTION_FIELD}" if missing else ""
        return view

    # ---- 写入 -----------------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if _is_blank(values.get(field))]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in BUSINESS_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._view(entry), []

    def update_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """补录或修改业务字段（如补齐上次年检、调整额定起重量）。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"起重机 {entry_id} 不存在或已归档"]
        invalid = [field for field in values if field not in EDITABLE_FIELDS]
        if invalid:
            return None, [f"字段「{'、'.join(invalid)}」不允许通过台账修改"]
        if "额定起重量" in values and not _is_blank(values.get("额定起重量")):
            if _as_number(values.get("额定起重量")) <= 0:
                return None, ["额定起重量必须是大于 0 的数值"]
        for field in EDITABLE_FIELDS:
            if field in values:
                entry[field] = str(values.get(field) or "").strip()
        return self._view(entry), []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"起重机 {entry_id} 不存在或已归档"
        values = values or {}
        current = str(entry.get("status") or STATUS_ORDER[0])

        if action == RESTORE_ACTION:
            return self._restore(entry, values, current)
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于起重机械可执行范围"

        target = ACTION_RULES[action]
        current_index = STATUS_ORDER.index(current) if current in STATUS_ORDER else 0
        target_index = STATUS_ORDER.index(target)

        # 状态只能顺着往下走一步：回退（超载/检验横跳）与跳步一律拦下。
        if target_index <= current_index:
            return None, f"起重机当前为「{current}」，不能执行「{action}」：状态只能沿 {' → '.join(STATUS_ORDER)} 顺序前进，不能回退"
        if target_index > current_index + 1:
            return None, f"起重机当前为「{current}」，不能直接{action}，需先完成「{STATUS_ORDER[current_index + 1]}」"

        # 安排检验、办理停用之前必须有上次年检日期；缺了就说明缺哪一项。
        if action in ("安排检验", "办理停用") and _is_blank(entry.get(INSPECTION_FIELD)):
            return None, f"缺少必填字段：{INSPECTION_FIELD}，请先补齐年检日期再{action}"

        # 降载运行可同时携带改小后的额定起重量，台账顺序随后按新值重排。
        if action == "降载运行":
            new_capacity = values.get("额定起重量")
            if new_capacity is not None and not _is_blank(new_capacity):
                if _as_number(new_capacity) <= 0:
                    return None, "额定起重量必须是大于 0 的数值"
                entry["额定起重量"] = str(new_capacity).strip()

        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._view(entry), f"起重机已{action}"

    def _restore(
        self, entry: dict[str, Any], values: dict[str, Any], current: str
    ) -> tuple[dict[str, Any] | None, str]:
        """已停用 → 正常：先补齐上次年检，且停用期间不许再被安排检验。"""
        if current != STATUS_ORDER[-1]:
            return None, f"起重机当前为「{current}」，仅「{STATUS_ORDER[-1]}」状态可恢复使用"
        if INSPECTION_FIELD in values and not _is_blank(values.get(INSPECTION_FIELD)):
            entry[INSPECTION_FIELD] = str(values[INSPECTION_FIELD]).strip()
        if _is_blank(entry.get(INSPECTION_FIELD)):
            return None, f"缺少必填字段：{INSPECTION_FIELD}，请先补齐年检日期再恢复使用"
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        return self._view(entry), "上次年检已补齐，起重机已恢复使用"
