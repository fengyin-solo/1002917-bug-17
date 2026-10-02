"""起重机械接口：维护起重机，覆盖降载运行、安排检验、办理停用、恢复使用等动作。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.crane import RESTORE_ACTION, CraneService

router = APIRouter(prefix="/api/crane", tags=["起重机械"])

service = CraneService()

LIST_FIELDS = ["起重机编号", "起重机类型", "额定起重量", "跨度", "工作级别", "操作人员", "上次年检", "起重机状态"]
STATUSES = ["正常", "超载运行", "检验中", "已停用"]
# 按状态顺序给出每个状态允许的动作，前端据此只放行可执行的操作。
AVAILABLE_ACTIONS = {
    "正常": ["降载运行"],
    "超载运行": ["安排检验"],
    "检验中": ["办理停用"],
    "已停用": [RESTORE_ACTION],
}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按起重机编号检索"),
    status: str | None = Query(default=None, description="正常、超载运行、检验中、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按起重机编号与状态过滤起重机械列表；台账按额定起重量排序，没有数据时返回空页。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict:
    """导出起重机械清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "crane", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条起重机明细；年检日期缺失时在返回里直接说明缺哪一项。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"起重机 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条起重机，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="起重机已登记", entry=entry)


@router.patch("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """补录或修改台账字段（如补齐上次年检、调整额定起重量）。"""
    entry, problems = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=problems[0] if problems else "起重机台账更新失败")
    return ActionResult(ok=True, message="起重机台账已更新", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条起重机执行动作；状态必须沿顺序前进，缺年检或跨状态都会被拦下并说明原因。"""
    values = dict(payload.values)
    # 兼容 {values: {action}} 与 {action} 两种提交方式。
    action = str(values.pop("action", "") or "").strip()
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
