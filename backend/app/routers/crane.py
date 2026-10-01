"""起重机械接口：维护起重机，覆盖降载运行、安排检验、办理停用、恢复使用等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.crane import CraneService

router = APIRouter(prefix="/api/crane", tags=["起重机械"])

service = CraneService()

LIST_FIELDS = ["起重机编号", "起重机类型", "额定起重量", "跨度", "工作级别", "操作人员", "上次年检", "起重机状态"]
STATUSES = ["正常", "超载运行", "检验中", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按起重机编号检索"),
    status: str | None = Query(default=None, description="正常、超载运行、检验中、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按起重机编号与状态过滤起重机械列表；列表按当前额定起重量从大到小排序。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出起重机械清单：返回当前过滤条件下的全量数据（同样按额定起重量排序）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "crane", "total": total, "items": items}


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict[str, Any]:
    """读取单条起重机明细；不存在时给出可读的错误说明，缺年检时一并报出缺项。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"起重机 {entry_id} 不存在或已归档")
    detail = dict(entry)
    missing = service.missing_fields(entry)
    detail["missing_fields"] = missing
    if missing:
        detail["missing_tip"] = f"缺少必填信息：{'、'.join(missing)}，请先补齐后再办理恢复使用"
    return detail


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条起重机，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="起重机已登记", entry=entry)


@router.patch("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改台账字段（调小额定起重量、补录上次年检等），修改后列表按新值重排。"""
    entry, message = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条起重机执行状态动作；跳序流转、停用后安排检验、年检未齐即恢复都会被拦下。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
