import sys
import os
import logging
import json
from fastapi import FastAPI, Request
import uvicorn

# 添加当前目录到path以便导入模块
sys.path.append(os.path.dirname(__file__))

from db import init_db
from composite import create_smart_sheet_and_sync, create_template_sheet_and_sync, create_bulk_sheets_and_sync, create_any_sheet_and_sync, delete_sheet_and_sync, update_record_and_sync, add_record_and_sync, delete_record_and_sync, SEAT_DATA

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= 可调参数 =================
CORP_ID = "ww742ff47a509b856e"
SECRET = "Iu6AYICGeiAe2kx3YyTSefTEZsld42U6EkGsQ2ON2QA"
DEFAULT_ADMIN_USERS = ["ChenDaHong"]  # 可指定初始管理员 userid 列表
BULK_SHEETS_MONTHS = 1  # 批量新建工作表时，默认创建未来几个月
SESSIONS = [("lunch", "午市"), ("dinner", "晚市")]  # 一天的市场配置：(session_type, 显示名)，按顺序创建
BULK_SHEETS_MAX_WORKERS = 5  # 批量创建工作表阶段二并发填充的并发数
# ===========================================

app = FastAPI()

# 初始化数据库
init_db()

@app.post("/create_doc")
async def tool_create_doc(request: Request):
    """工具1：新建智能表格并同步数据库"""
    try:
        body = await request.json()
        doc_name = body.get("doc_name", "订座信息表")
        admin_users = body.get("admin_users", DEFAULT_ADMIN_USERS)
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        result = create_smart_sheet_and_sync(
            CORP_ID, SECRET, doc_name, admin_users,
            operator_userid, operator_name
        )
        return {
            "content": f"✅ 成功创建智能表格「{doc_name}」\n📎 访问链接：{result['doc_url']}",
            "doc_id": result["doc_id"],
            "doc_url": result["doc_url"]
        }
    except Exception as e:
        logging.error(f"创建智能表格失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.post("/create_template")
async def tool_create_template(request: Request):
    """工具2：在第一个智能表格中创建模板工作表并初始化数据"""
    try:
        body = await request.json()
        template_name = body.get("template_name", "订座信息表模板")
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        result = create_template_sheet_and_sync(
            CORP_ID, SECRET, template_name,
            operator_userid, operator_name
        )
        return {
            "content": f"✅ 成功创建模板工作表「{template_name}」\n📄 已填入 {len(SEAT_DATA)} 条座位记录",
            "sheet_id": result["sheet_id"]
        }
    except Exception as e:
        logging.error(f"创建模板工作表失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.post("/create_bulk_sheets")
async def tool_create_bulk_sheets(request: Request):
    """工具3：批量新建工作表（三阶段流水线加速，默认未来三个月，每天午市+晚市）"""
    try:
        body = await request.json()
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")
        months = body.get("months", BULK_SHEETS_MONTHS)
        sessions = body.get("sessions", SESSIONS)
        max_workers = body.get("max_workers", BULK_SHEETS_MAX_WORKERS)

        result = create_bulk_sheets_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            months=months, sessions=sessions, max_workers=max_workers
        )
        # 构造分阶段统计信息
        msg = (
            f"✅ 批量创建完成：{result['start_date']} ~ {result['end_date']}\n"
            f"📊 三阶段流水线统计（并发数 {result['max_workers']}）：\n"
            f"  阶段一（串行创建子表）：成功 {result['total'] - result['phase1_failed_count']} 张，失败 {result['phase1_failed_count']} 张\n"
            f"  阶段二（并发填充）：成功 {result['phase2_success_count']} 张，失败 {result['total'] - result['phase1_failed_count'] - result['phase2_success_count']} 张\n"
            f"  阶段三（串行重试）：重试成功 {result['phase3_retry_success_count']} 张，重试失败 {result['phase3_retry_failed_count']} 张\n"
            f"  最终结果：成功 {result['final_success_count']} 张，失败 {result['final_failed_count']} 张"
        )
        # 失败明细（阶段一 + 阶段三重试失败）
        failed_details = result["phase1_failed"] + result["phase3_retry_failed"]
        if failed_details:
            failed_summary = "；".join(
                f"{f['sheet_name']}({f['error'][:30]})" for f in failed_details[:5]
            )
            msg += f"\n⚠️ 失败明细（前5条）：{failed_summary}"
        # 重试成功明细
        if result["phase3_retry_success"]:
            retry_summary = "、".join(s["sheet_name"] for s in result["phase3_retry_success"][:5])
            msg += f"\n🔁 重试成功（前5条）：{retry_summary}"
        return {
            "content": msg,
            "total": result["total"],
            "max_workers": result["max_workers"],
            "phase1_failed_count": result["phase1_failed_count"],
            "phase2_success_count": result["phase2_success_count"],
            "phase3_retry_success_count": result["phase3_retry_success_count"],
            "phase3_retry_failed_count": result["phase3_retry_failed_count"],
            "final_success_count": result["final_success_count"],
            "final_failed_count": result["final_failed_count"],
            "phase1_failed": result["phase1_failed"],
            "phase3_retry_success": result["phase3_retry_success"],
            "phase3_retry_failed": result["phase3_retry_failed"],
            "start_date": result["start_date"],
            "end_date": result["end_date"]
        }
    except Exception as e:
        logging.error(f"批量创建工作表失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.post("/create_sheet")
async def tool_create_sheet(request: Request):
    """工具4：针对第一个智能表格，按任意日期新建工作表（默认午市+晚市，可单独指定）

    校验规则：
      1. 不允许新建当前日期之前的工作表（如今天 6-2，则 6-1 及之前报错）
      2. 不允许与现有工作表命名重复（任一命中即报错，不会局部创建）

    请求 Body（JSON）示例：
      - 创建 2026-09-26 的午市+晚市（默认两张表）：
        {"date": "2026-09-26", "operator_userid": "xxx", "operator_name": "yyy"}
      - 创建 9-26 的晚市仅一张（简写 MM-DD，自动用当年）：
        {"date": "9-26", "sessions": ["dinner"], "operator_userid": "xxx", "operator_name": "yyy"}
      - sessions 支持 ["lunch", "dinner"] / ["午市", "晚市"] / ["lunch"] / "午市" 等多种写法
    """
    try:
        body = await request.json()
        sheet_date = body.get("date")
        if not sheet_date:
            return {"content": "❌ 参数错误：请提供 date，格式示例 '2026-09-26' 或 '9-26'"}
        sessions = body.get("sessions", None)  # None → 用默认 SESSIONS（午市+晚市）
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        result = create_any_sheet_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            sheet_date=sheet_date,
            sessions=sessions,
            default_sessions=SESSIONS,
        )

        # 构造友好的返回内容
        created_lines = []
        for s in result["sheets"]:
            stype_label = dict(SESSIONS).get(s["session_type"], s["session_type"])
            created_lines.append(f"  · {s['sheet_name']}（{stype_label}）")

        msg = (
            f"✅ 成功新建 {result['created_count']} 张工作表\n"
            f"📅 日期：{result['date']}（{result['weekday']}）\n"
            + "\n".join(created_lines)
        )

        return {
            "content": msg,
            "date": result["date"],
            "weekday": result["weekday"],
            "created_count": result["created_count"],
            "sheets": result["sheets"],
        }
    except Exception as e:
        logging.error(f"新建工作表失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.post("/delete_sheet")
async def tool_delete_sheet(request: Request):
    """工具5：删除数据库第一个智能表格中的指定工作表

    校验规则：
      1. 必须提供 sheet_name 或 sheet_id 之一
      2. 工作表必须在本地 sheets 表中存在
      3. 不允许删除模板工作表（templates 表中的记录一律拒绝）
      4. 不允许删除文档内最后一张子表（企业微信限制）

    请求 Body（JSON）示例：
      - 按名称删除（推荐）：
        {"sheet_name": "9-26晚市周六", "operator_userid": "xxx", "operator_name": "yyy"}
      - 按 sheet_id 删除：
        {"sheet_id": "xxxxxx", "operator_userid": "xxx", "operator_name": "yyy"}
      - 同时提供时以 sheet_id 为准
    """
    try:
        body = await request.json()
        sheet_name = body.get("sheet_name")
        sheet_id = body.get("sheet_id")
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        if not sheet_name and not sheet_id:
            return {"content": "❌ 参数错误：请提供 sheet_name 或 sheet_id 之一"}

        result = delete_sheet_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            sheet_name=sheet_name,
            sheet_id=sheet_id,
        )

        msg = (
            f"✅ 成功删除工作表\n"
            f"📄 工作表：{result['sheet_name']}\n"
            f"🔖 sheet_id：{result['sheet_id']}\n"
            f"🕒 删除时间：{result['deleted_at']}"
        )
        return {
            "content": msg,
            "sheet_id": result["sheet_id"],
            "sheet_name": result["sheet_name"],
            "deleted_at": result["deleted_at"],
        }
    except Exception as e:
        logging.error(f"删除工作表失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.post("/update_record")
async def tool_update_record(request: Request):
    """工具6：更新指定工作表中指定座位记录的字段值（订座信息）

    自动应用订座规则：
      - 客人称呼/客人电话/人数/留菜/留位人 任一非空 → "是否已订"自动设为"已订座"
      - 全部为空 → "是否已订"自动设为"未订座"
      （判断基于更新后的最终值，即当前值 + 更新值合并后）

    请求 Body（JSON）示例：
      - 订座（填入客人信息）：
        {"date": "2026-09-26", "session": "dinner", "seat_name": "北京房",
         "fields": {"客人称呼": "张三", "客人电话": "13800138000", "人数": "8"},
         "operator_userid": "xxx", "operator_name": "yyy"}

      - 取消订座（清空客人信息）：
        {"date": "2026-09-26", "session": "dinner", "seat_name": "北京房",
         "fields": {"客人称呼": "", "客人电话": "", "人数": "", "留菜": "", "留位人": ""},
         "operator_userid": "xxx", "operator_name": "yyy"}

    参数说明：
      - date:    日期（YYYY-MM-DD / MM-DD）
      - session: 场次（lunch/dinner/午市/晚市）
      - seat_name: 座位名称（如"北京房"）
      - fields:  要更新的字段字典，支持任意字段名
    """
    try:
        body = await request.json()
        sheet_date = body.get("date")
        session = body.get("session")
        seat_name = body.get("seat_name")
        fields = body.get("fields", {})
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        if not sheet_date:
            return {"content": "❌ 参数错误：请提供 date"}
        if not session:
            return {"content": "❌ 参数错误：请提供 session（lunch/dinner/午市/晚市）"}
        if not seat_name:
            return {"content": "❌ 参数错误：请提供 seat_name"}
        if not fields:
            return {"content": "❌ 参数错误：请提供 fields（要更新的字段）"}

        result = update_record_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            sheet_date=sheet_date,
            session=session,
            seat_name=seat_name,
            fields=fields,
            default_sessions=SESSIONS,
        )

        updated_lines = []
        for k, v in result["updated_fields"].items():
            updated_lines.append(f"  · {k}：{v}")

        msg = (
            f"✅ 成功更新订座信息\n"
            f"📅 工作表：{result['sheet_name']}\n"
            f"🪑 座位：{result['seat_name']}\n"
            f"📝 更新字段：\n"
            + "\n".join(updated_lines)
            + f"\n🔔 订座状态：{result['booking_status']}"
        )

        return {
            "content": msg,
            "sheet_name": result["sheet_name"],
            "seat_name": result["seat_name"],
            "record_id": result["record_id"],
            "updated_fields": result["updated_fields"],
            "booking_status": result["booking_status"],
        }
    except Exception as e:
        logging.error(f"更新记录失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.post("/add_record")
async def tool_add_record(request: Request):
    """工具7：向指定工作表添加一条新记录

    默认值：
      - 座位名称 = 传入的 seat_name
      - 座位类型 = "大厅"
      - 是否已订 = "未订座"（自动按订座规则计算）
      - 其余字段 = 空

    订座规则（自动应用）：
      - 客人称呼/客人电话/人数/留菜/留位人 任一非空 → "是否已订" = "已订座"
      - 全部为空 → "是否已订" = "未订座"

    请求 Body（JSON）示例：
      - 添加空白座位（全部默认值）：
        {"date": "2026-09-26", "session": "dinner", "seat_name": "临时桌A",
         "operator_userid": "xxx", "operator_name": "yyy"}

      - 添加并填写客人信息：
        {"date": "2026-09-26", "session": "dinner", "seat_name": "临时桌B",
         "fields": {"客人称呼": "王五", "客人电话": "13900000000", "人数": "4", "座位类型": "房间"},
         "operator_userid": "xxx", "operator_name": "yyy"}
    """
    try:
        body = await request.json()
        sheet_date = body.get("date")
        session = body.get("session")
        seat_name = body.get("seat_name")
        fields = body.get("fields", {})
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        if not sheet_date:
            return {"content": "❌ 参数错误：请提供 date"}
        if not session:
            return {"content": "❌ 参数错误：请提供 session（lunch/dinner/午市/晚市）"}
        if not seat_name:
            return {"content": "❌ 参数错误：请提供 seat_name"}

        result = add_record_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            sheet_date=sheet_date,
            session=session,
            seat_name=seat_name,
            fields=fields,
            default_sessions=SESSIONS,
        )

        field_lines = []
        for k, v in result["fields"].items():
            field_lines.append(f"  · {k}：{v}")

        msg = (
            f"✅ 成功添加记录\n"
            f"📅 工作表：{result['sheet_name']}\n"
            f"🪑 座位：{result['seat_name']}\n"
            f"🔖 record_id：{result['record_id']}\n"
            f"📝 记录内容：\n"
            + "\n".join(field_lines)
            + f"\n🔔 订座状态：{result['booking_status']}"
        )

        return {
            "content": msg,
            "sheet_name": result["sheet_name"],
            "seat_name": result["seat_name"],
            "record_id": result["record_id"],
            "fields": result["fields"],
            "booking_status": result["booking_status"],
        }
    except Exception as e:
        logging.error(f"添加记录失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.post("/delete_record")
async def tool_delete_record(request: Request):
    """工具8：从指定工作表删除指定记录

    定位方式（二选一，record_id 优先）：
      - record_id: 直接按记录 ID 删除
      - seat_name:  按座位名称查找后删除

    请求 Body（JSON）示例：
      - 按座位名称删除：
        {"date": "2026-09-26", "session": "dinner", "seat_name": "临时桌A",
         "operator_userid": "xxx", "operator_name": "yyy"}

      - 按 record_id 删除：
        {"date": "2026-09-26", "session": "dinner", "record_id": "recXXXXXX",
         "operator_userid": "xxx", "operator_name": "yyy"}
    """
    try:
        body = await request.json()
        sheet_date = body.get("date")
        session = body.get("session")
        seat_name = body.get("seat_name")
        record_id = body.get("record_id")
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        if not sheet_date:
            return {"content": "❌ 参数错误：请提供 date"}
        if not session:
            return {"content": "❌ 参数错误：请提供 session（lunch/dinner/午市/晚市）"}
        if not record_id and not seat_name:
            return {"content": "❌ 参数错误：请提供 record_id 或 seat_name 之一"}

        result = delete_record_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            sheet_date=sheet_date,
            session=session,
            seat_name=seat_name,
            record_id=record_id,
            default_sessions=SESSIONS,
        )

        msg = (
            f"✅ 成功删除记录\n"
            f"📅 工作表：{result['sheet_name']}\n"
            f"🪑 座位：{result['seat_name'] or '（按record_id删除）'}\n"
            f"🔖 record_id：{result['deleted_record_id']}\n"
            f"🕒 删除时间：{result['deleted_at']}"
        )

        return {
            "content": msg,
            "sheet_name": result["sheet_name"],
            "deleted_record_id": result["deleted_record_id"],
            "seat_name": result["seat_name"],
            "deleted_at": result["deleted_at"],
        }
    except Exception as e:
        logging.error(f"删除记录失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)