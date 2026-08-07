import sys
import os
import logging
import json
from fastapi import FastAPI, Request
import uvicorn

# 添加当前目录到path以便导入模块
sys.path.append(os.path.dirname(__file__))

from db import init_db
from composite import create_smart_sheet_and_sync, create_template_sheet_and_sync, create_bulk_sheets_and_sync, SEAT_DATA

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= 可调参数 =================
CORP_ID = "ww742ff47a509b856e"
SECRET = "Iu6AYICGeiAe2kx3YyTSefTEZsld42U6EkGsQ2ON2QA"
DEFAULT_ADMIN_USERS = ["ChenDaHong"]  # 可指定初始管理员 userid 列表
BULK_SHEETS_MONTHS = 3  # 批量新建工作表时，默认创建未来几个月
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

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)