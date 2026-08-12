import sys
import os
import logging
import json
from datetime import date, datetime, timedelta, timezone
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import uvicorn

# ================= 可选依赖兜底：APScheduler + pytz =================
# 若未安装，只禁用"每日零点定时任务"，其余接口不受影响（避免启动即崩溃）
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    _HAS_SCHEDULER = True
except ImportError:
    BackgroundScheduler = None  # type: ignore
    CronTrigger = None          # type: ignore
    _HAS_SCHEDULER = False

try:
    import pytz as _pytz
    _HAS_PYTZ = True
except ImportError:
    _pytz = None  # type: ignore
    _HAS_PYTZ = False
# =====================================================================

# 添加当前目录到path以便导入模块
sys.path.append(os.path.dirname(__file__))

from db import init_db
from composite import (
    create_smart_sheet_and_sync,
    create_template_sheet_and_sync,
    create_bulk_sheets_and_sync,
    create_any_sheet_and_sync,
    delete_sheet_and_sync,
    update_record_and_sync,
    add_record_and_sync,
    delete_record_and_sync,
    query_records_and_sync,
    SEAT_DATA,
    # buffer 管理相关
    buffer_manage_and_sync,
    set_time_offset_days,
    clear_time_offset_days,
    get_time_offset_days,
    get_virtual_today,
    get_virtual_now,
    MAX_SHEETS_LIMIT,
    BUFFER_DAYS_PAST,
    # 回调同步
    sync_remote_record_change,
    sync_remote_record_delete,
)
import wecom_callback

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 可选依赖缺失时打印 WARN（不抛错，继续启动）
if not _HAS_SCHEDULER:
    logging.warning("[可选依赖] 未安装 APScheduler：每日零点定时任务已禁用，可手动调用 /test/trigger_buffer 触发")
if not _HAS_PYTZ:
    logging.warning("[可选依赖] 未安装 pytz：将使用 UTC+8 固定偏移作为北京时间兜底（建议安装 pytz 以处理夏令时等边界）")

# ================= 可调参数 =================
CORP_ID = "ww742ff47a509b856e"
SECRET = "Iu6AYICGeiAe2kx3YyTSefTEZsld42U6EkGsQ2ON2QA"
DEFAULT_ADMIN_USERS = ["ChenDaHong"]  # 可指定初始管理员 userid 列表
BULK_SHEETS_DAYS = 30  # 批量新建工作表时，默认创建未来几天（含今天）
SESSIONS = [("lunch", "午市"), ("dinner", "晚市")]  # 一天的市场配置：(session_type, 显示名)，按顺序创建
BULK_SHEETS_MAX_WORKERS = 5  # 批量创建工作表阶段二并发填充的并发数

# ---- buffer 自动管理参数 ----
BUFFER_SCHEDULE_HOUR = 0    # 每日执行小时（北京时间，默认 0 = 零点）
BUFFER_SCHEDULE_MINUTE = 0  # 每日执行分钟（默认 0 分）
BUFFER_DAYS_FUTURE = BULK_SHEETS_DAYS  # buffer 未来几天（含今天），默认与批量创建保持一致
BUFFER_PAST_DAYS = BUFFER_DAYS_PAST  # buffer 过去几天（不含今天）

# ---- 回调同步参数 ----
# 在企业微信后台「自建应用 → 接收消息 → 设置API接收」中配置
CALLBACK_TOKEN = "ryaWSkQqLtgzlDFylCF596b9kmxG"                # 回调 Token（后台生成或手动填写）
CALLBACK_ENCODING_AES_KEY = "Pmx11AhQn3fYQh1zTi7bxS1XCuiLMbA5vC8Fesqi8Bz"     # 回调 EncodingAESKey（43位，后台生成或手动填写）

# ---- 字段英文↔中文双向映射（仅 /update_record /add_record 接口层翻译，内部 composite 仍用中文）----
FIELD_KEY_EN_TO_ZH = {
    "seat_name": "座位名称",
    "seat_capacity": "座位容量",
    "seat_remark": "座位备注",
    "guest_name": "客人称呼",
    "guest_phone": "客人电话",
    "guest_count": "人数",
    "reserved_dishes": "留菜",
    "reserved_by": "留位人",
    "seat_type": "座位类型",
    "booking_status": "是否已订",
}
FIELD_KEY_ZH_TO_EN = {zh: en for en, zh in FIELD_KEY_EN_TO_ZH.items()}


def _translate_fields_keys(d: dict, mapping: dict, strict: bool = False) -> dict:
    """翻译字典 key，忽略不在 mapping 中的 key（strict=False 时原样保留）。
    strict=True 时，遇到未知 key 会抛 ValueError（用于入参校验）。"""
    if not d:
        return {}
    result = {}
    for k, v in d.items():
        if k in mapping:
            result[mapping[k]] = v
        else:
            if strict:
                raise ValueError(
                    f"未知字段 key：{k!r}，有效值为：{sorted(mapping.keys())}"
                )
            result[k] = v
    return result


def _fields_en_to_zh(d: dict, strict: bool = False) -> dict:
    """输入层：英文字典 key → 中文 key，交给 composite 处理"""
    return _translate_fields_keys(d, FIELD_KEY_EN_TO_ZH, strict=strict)


def _fields_zh_to_en(d: dict, strict: bool = False) -> dict:
    """输出层：中文字典 key → 英文 key，返回给大模型/调用方"""
    return _translate_fields_keys(d, FIELD_KEY_ZH_TO_EN, strict=strict)
# ===========================================

app = FastAPI()

# 初始化数据库
init_db()

logging.info(f"[启动] buffer 参数：未来 {BUFFER_DAYS_FUTURE} 天，过去 {BUFFER_PAST_DAYS} 天，"
             f"每日 {BUFFER_SCHEDULE_HOUR:02d}:{BUFFER_SCHEDULE_MINUTE:02d} 北京时间执行")


# ================= APScheduler 定时任务 =================
def _buffer_job_wrapper():
    """定时任务包装器：捕获异常避免 scheduler 崩溃"""
    try:
        logging.info("[定时任务] ==== 触发每日零点 buffer 管理 ====")
        result = buffer_manage_and_sync(
            corp_id=CORP_ID,
            secret=SECRET,
            operator_userid="scheduler",
            operator_name="定时任务",
            days=BUFFER_DAYS_FUTURE,
            sessions=SESSIONS,
            past_days=BUFFER_PAST_DAYS,
        )
        logging.info(f"[定时任务] buffer 管理完成：总表数 "
                     f"{result['total_sheets_before']} → {result['total_sheets_after']}")
    except Exception as e:
        logging.error(f"[定时任务] buffer 管理执行失败：{e}", exc_info=True)


def _get_beijing_tz():
    """获取北京时区：优先 pytz（精确处理夏令时/历史时区），缺失则用 UTC+8 固定偏移兜底"""
    if _HAS_PYTZ:
        return _pytz.timezone("Asia/Shanghai")
    # 兜底：北京时间 = UTC+8 固定偏移
    return timezone(timedelta(hours=8), name="Asia/Shanghai(UTC+8)")


def _start_scheduler():
    """启动 APScheduler，每日北京时间零点执行 buffer_manage_and_sync
    可选依赖兜底：未安装 APScheduler 时直接跳过（不抛错，返回 None）
    """
    if not _HAS_SCHEDULER:
        logging.warning("[定时任务] APScheduler 未安装，跳过启动；请通过 /test/trigger_buffer 手动触发 buffer 管理")
        return None
    try:
        tz = _get_beijing_tz()
        scheduler = BackgroundScheduler(timezone=tz)

        trigger = CronTrigger(
            hour=BUFFER_SCHEDULE_HOUR,
            minute=BUFFER_SCHEDULE_MINUTE,
            second=0,
            timezone=tz,
        )
        scheduler.add_job(
            _buffer_job_wrapper,
            trigger=trigger,
            id="daily_buffer_manage",
            name="每日零点 buffer 自动管理",
            replace_existing=True,
        )
        scheduler.start()

        now = datetime.now(tz)
        next_run = now.replace(
            hour=BUFFER_SCHEDULE_HOUR,
            minute=BUFFER_SCHEDULE_MINUTE,
            second=0,
            microsecond=0,
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        logging.info(f"[定时任务] APScheduler 启动成功，下次执行时间（北京时间）：{next_run.isoformat()}")
        return scheduler
    except Exception as e:
        logging.error(f"[定时任务] APScheduler 启动失败：{e}", exc_info=True)
        return None


scheduler = _start_scheduler()
app.state.scheduler = scheduler

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
    """工具3：批量新建工作表（三阶段流水线加速，默认未来90天，每天午市+晚市）"""
    try:
        body = await request.json()
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")
        days = body.get("days", BULK_SHEETS_DAYS)
        sessions = body.get("sessions", SESSIONS)
        max_workers = body.get("max_workers", BULK_SHEETS_MAX_WORKERS)

        result = create_bulk_sheets_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            days=days, sessions=sessions, max_workers=max_workers
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

    定位方式（三选一，优先级从高到低）：
      1. date + session   → 日期+场次定位（推荐，不需要记工作表全名）
      2. sheet_id         → 按工作表 ID（最精确）
      3. sheet_name       → 按工作表全名（兼容旧写法）

    校验规则：
      1. 必须提供 (date+session) 或 sheet_name 或 sheet_id 之一
      2. 工作表必须在本地 sheets 表中存在
      3. 不允许删除模板工作表（templates 表中的记录一律拒绝）
      4. 不允许删除文档内最后一张子表（企业微信限制）

    请求 Body（JSON）示例：
      - 按日期+场次删除（推荐）：
        {"date": "2026-09-26", "session": "dinner", "operator_userid": "xxx", "operator_name": "yyy"}
        {"date": "9-26", "session": "晚市", "operator_userid": "xxx", "operator_name": "yyy"}
      - 按名称删除（兼容旧逻辑）：
        {"sheet_name": "9-26晚市周六", "operator_userid": "xxx", "operator_name": "yyy"}
      - 按 sheet_id 删除：
        {"sheet_id": "xxxxxx", "operator_userid": "xxx", "operator_name": "yyy"}
      - 同时提供多种时：date+session > sheet_id > sheet_name
    """
    try:
        body = await request.json()
        sheet_date = body.get("date")
        session = body.get("session")
        sheet_name = body.get("sheet_name")
        sheet_id = body.get("sheet_id")
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        if not sheet_name and not sheet_id and not (sheet_date and session):
            return {"content": "❌ 参数错误：请提供 date+session 或 sheet_name 或 sheet_id 之一"}

        result = delete_sheet_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            sheet_name=sheet_name,
            sheet_id=sheet_id,
            sheet_date=sheet_date,
            session=session,
            default_sessions=SESSIONS,
        )

        # 定位方式的中文说明（便于给大模型看）
        located_label = {
            "date_session": "日期+场次",
            "sheet_id": "sheet_id",
            "sheet_name": "工作表名称",
        }.get(result.get("located_by"), result.get("located_by", ""))

        msg = (
            f"✅ 成功删除工作表\n"
            f"📄 工作表：{result['sheet_name']}\n"
            f"🔖 sheet_id：{result['sheet_id']}\n"
            f"🧭 定位方式：{located_label}\n"
            f"🕒 删除时间：{result['deleted_at']}"
        )
        return {
            "content": msg,
            "sheet_id": result["sheet_id"],
            "sheet_name": result["sheet_name"],
            "deleted_at": result["deleted_at"],
            "located_by": result["located_by"],
        }
    except Exception as e:
        logging.error(f"删除工作表失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.post("/update_record")
async def tool_update_record(request: Request):
    """工具6：更新指定工作表中指定座位记录的字段值（订座信息）

    自动应用订座规则：
      - guest_name/guest_phone/guest_count/reserved_dishes/reserved_by 任一非空
        → booking_status 自动设为 "已订座"
      - 全部为空 → booking_status 自动设为 "未订座"
      （判断基于更新后的最终值，即当前值 + 更新值合并后）

    请求 Body（JSON）示例：
      - 订座（填入客人信息）：
        {"date": "2026-09-26", "session": "dinner", "seat_name": "北京房",
         "fields": {"guest_name": "张三", "guest_phone": "13800138000", "guest_count": "8"},
         "operator_userid": "xxx", "operator_name": "yyy"}

      - 取消订座（清空客人信息）：
        {"date": "2026-09-26", "session": "dinner", "seat_name": "北京房",
         "fields": {"guest_name": "", "guest_phone": "", "guest_count": "", "reserved_dishes": "", "reserved_by": ""},
         "operator_userid": "xxx", "operator_name": "yyy"}

    参数说明：
      - date:    日期（YYYY-MM-DD / MM-DD）
      - session: 场次（lunch/dinner/午市/晚市）
      - seat_name: 座位名称（如"北京房"）
      - fields:  要更新的字段字典，支持的英文 key：
                 seat_name, seat_capacity, seat_remark, guest_name, guest_phone,
                 guest_count, reserved_dishes, reserved_by, seat_type, booking_status
    """
    try:
        body = await request.json()
        sheet_date = body.get("date")
        session = body.get("session")
        seat_name = body.get("seat_name")
        fields_en = body.get("fields", {})
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        if not sheet_date:
            return {"content": "❌ 参数错误：请提供 date"}
        if not session:
            return {"content": "❌ 参数错误：请提供 session（lunch/dinner/午市/晚市）"}
        if not seat_name:
            return {"content": "❌ 参数错误：请提供 seat_name"}
        if not fields_en:
            return {"content": "❌ 参数错误：请提供 fields（要更新的字段）"}

        # 输入层：英文 key → 中文 key，交给内部逻辑处理
        try:
            fields_zh = _fields_en_to_zh(fields_en, strict=True)
        except ValueError as ve:
            return {"content": f"❌ 参数错误：{str(ve)}"}

        result = update_record_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            sheet_date=sheet_date,
            session=session,
            seat_name=seat_name,
            fields=fields_zh,
            default_sessions=SESSIONS,
        )

        # 输出层：中文 key → 英文 key，返回给调用方
        updated_fields_en = _fields_zh_to_en(result["updated_fields"])

        updated_lines = []
        for k, v in updated_fields_en.items():
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
            "updated_fields": updated_fields_en,
            "booking_status": result["booking_status"],
        }
    except Exception as e:
        logging.error(f"更新记录失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.post("/add_record")
async def tool_add_record(request: Request):
    """工具7：向指定工作表添加一条新记录

    默认值：
      - seat_name = 传入的 seat_name
      - seat_type = "大厅"
      - booking_status = "未订座"（自动按订座规则计算）
      - 其余字段 = 空

    订座规则（自动应用）：
      - guest_name/guest_phone/guest_count/reserved_dishes/reserved_by 任一非空
        → booking_status = "已订座"
      - 全部为空 → booking_status = "未订座"

    请求 Body（JSON）示例：
      - 添加空白座位（全部默认值）：
        {"date": "2026-09-26", "session": "dinner", "seat_name": "临时桌A",
         "operator_userid": "xxx", "operator_name": "yyy"}

      - 添加并填写客人信息：
        {"date": "2026-09-26", "session": "dinner", "seat_name": "临时桌B",
         "fields": {"guest_name": "王五", "guest_phone": "13900000000", "guest_count": "4", "seat_type": "房间"},
         "operator_userid": "xxx", "operator_name": "yyy"}

    fields 支持的英文 key：
      seat_name, seat_capacity, seat_remark, guest_name, guest_phone,
      guest_count, reserved_dishes, reserved_by, seat_type, booking_status
    """
    try:
        body = await request.json()
        sheet_date = body.get("date")
        session = body.get("session")
        seat_name = body.get("seat_name")
        fields_en = body.get("fields", {})
        operator_userid = body.get("operator_userid", "system")
        operator_name = body.get("operator_name", "系统")

        if not sheet_date:
            return {"content": "❌ 参数错误：请提供 date"}
        if not session:
            return {"content": "❌ 参数错误：请提供 session（lunch/dinner/午市/晚市）"}
        if not seat_name:
            return {"content": "❌ 参数错误：请提供 seat_name"}

        # 输入层：英文 key → 中文 key，交给内部逻辑处理
        try:
            fields_zh = _fields_en_to_zh(fields_en, strict=True)
        except ValueError as ve:
            return {"content": f"❌ 参数错误：{str(ve)}"}

        result = add_record_and_sync(
            CORP_ID, SECRET, operator_userid, operator_name,
            sheet_date=sheet_date,
            session=session,
            seat_name=seat_name,
            fields=fields_zh,
            default_sessions=SESSIONS,
        )

        # 输出层：中文 key → 英文 key，返回给调用方
        fields_en_out = _fields_zh_to_en(result["fields"])

        field_lines = []
        for k, v in fields_en_out.items():
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
            "fields": fields_en_out,
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

@app.post("/query_records")
async def tool_query_records(request: Request):
    """工具9：查询工作表所有记录

    返回格式化的 Markdown 表格 + 统计摘要，直接供大模型理解。

    请求 Body（JSON）示例：
      {"date": "2026-09-26", "session": "dinner"}

    session 支持：lunch / dinner / 午市 / 晚市
    date 支持：2026-09-26 / 9-26 / 2026/9/26 等格式
    """
    try:
        body = await request.json()
        sheet_date = body.get("date")
        session = body.get("session")

        if not sheet_date:
            return {"content": "❌ 参数错误：请提供 date"}
        if not session:
            return {"content": "❌ 参数错误：请提供 session（lunch/dinner/午市/晚市）"}

        result = query_records_and_sync(
            CORP_ID, SECRET,
            sheet_date=sheet_date,
            session=session,
            default_sessions=SESSIONS,
        )

        return {
            "content": result["content"],
            "sheet_name": result["sheet_name"],
            "total": result["total"],
            "booked_count": result["booked_count"],
            "available_count": result["available_count"],
        }
    except Exception as e:
        logging.error(f"查询工作表记录失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}


# ============================================================
# 企业微信回调：接收记录变更事件，自动同步本地数据库
# 这是内部自动化端点，不对外暴露为工具
# ============================================================

def _get_callback_crypt():
    """创建回调官方 SDK 实例；若未配置则返回 None"""
    if not CALLBACK_TOKEN or not CALLBACK_ENCODING_AES_KEY:
        logging.error("[回调] CALLBACK_TOKEN 或 CALLBACK_ENCODING_AES_KEY 未配置")
        return None
    try:
        return wecom_callback.make_crypt(CALLBACK_TOKEN, CALLBACK_ENCODING_AES_KEY, CORP_ID)
    except Exception as e:
        logging.error(f"[回调] 初始化 SDK 失败: {e}")
        return None


@app.get("/callback/wecom")
async def verify_callback_url(msg_signature: str, timestamp: str, nonce: str, echostr: str):
    """企业微信后台配置回调URL时的验证接口（GET）

    企业微信会发送 GET 请求，携带 msg_signature / timestamp / nonce / echostr。
    验证签名通过后，解密 echostr 并返回明文。

    注意：无论验证是否通过，都返回 200 + 明文（或空串），与 test 目录的已跑通实现对齐。
    企业微信要求：验证失败时不能返回 403/500，否则提示回调地址请求不通过。
    """
    logging.info("=== [回调] 收到 URL 验证请求 ===")
    wxcpt = _get_callback_crypt()
    if not wxcpt:
        return PlainTextResponse(content="", status_code=200)
    try:
        plain = wecom_callback.verify_url(wxcpt, msg_signature, timestamp, nonce, echostr)
        logging.info(f"[回调] URL 验证通过，返回内容: {plain}")
        return PlainTextResponse(content=plain, status_code=200)
    except Exception as e:
        logging.error(f"[回调] URL验证失败: {e}")
        return PlainTextResponse(content="", status_code=200)


@app.post("/callback/wecom")
async def receive_callback(msg_signature: str, timestamp: str, nonce: str, request: Request):
    """接收企业微信记录变更回调（POST）

    企业微信在用户修改/新增/删除智能表格记录时，推送此回调。
    回调内容为加密 XML，验签解密后解析出变更详情，调用 composite 同步函数。

    响应必须返回纯文本 "success"（或空串），状态码 200，否则企业微信会重试。
    """
    wxcpt = _get_callback_crypt()
    if not wxcpt:
        return PlainTextResponse(content="success", status_code=200)

    try:
        body = await request.body()

        # 验签 + 解密 + 解析（全部走官方 SDK）
        callback_data = wecom_callback.parse_callback(
            wxcpt,
            msg_signature=msg_signature,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        )

        event = callback_data.get("event", "")
        change_type = callback_data.get("change_type", "")

        # 只处理智能表格记录变更事件
        if event != "smart_sheet_change":
            logging.info(f"[回调] 非智能表格事件，跳过: event={event}")
            return PlainTextResponse("success", status_code=200)

        doc_id = callback_data["doc_id"]
        sheet_id = callback_data["sheet_id"]
        record_ids = callback_data["record_ids"]
        from_user = callback_data["from_user"]

        if not record_ids:
            logging.info("[回调] record_ids 为空，跳过")
            return PlainTextResponse("success", status_code=200)

        # 分发到对应的同步函数
        if change_type in ("update_record", "add_record"):
            sync_remote_record_change(
                corp_id=CORP_ID,
                secret=SECRET,
                doc_id=doc_id,
                sheet_id=sheet_id,
                record_ids=record_ids,
                operator_userid=from_user,
                change_type=change_type,
                default_sessions=SESSIONS,
            )
        elif change_type == "delete_record":
            sync_remote_record_delete(
                corp_id=CORP_ID,
                secret=SECRET,
                doc_id=doc_id,
                sheet_id=sheet_id,
                record_ids=record_ids,
                operator_userid=from_user,
                default_sessions=SESSIONS,
            )
        else:
            logging.info(f"[回调] 未知 ChangeType，跳过: {change_type}")

        return PlainTextResponse("success", status_code=200)

    except Exception as e:
        # 即使处理失败也返回 success，避免企业微信重试
        # （重试不会修复代码bug，只会造成重复日志）
        logging.error(f"[回调] 处理失败: {e}", exc_info=True)
        return PlainTextResponse("success", status_code=200)


# ============================================================
# 测试接口：时间偏移 + 手动触发 buffer
# ============================================================

@app.post("/test/set_time_offset")
async def test_set_time_offset(request: Request):
    """测试接口：设置时间偏移（天数），模拟日期跳转
    正数 = 跳到未来 N 天，负数 = 回到过去 N 天，0 = 不偏移

    请求 Body 示例：
      {"offset_days": 30}   → 虚拟今天 = 真实今天 + 30 天
      {"offset_days": -7}   → 虚拟今天 = 真实今天 - 7 天
    """
    try:
        body = await request.json()
        offset_days = body.get("offset_days")
        if offset_days is None:
            return {"content": "❌ 参数错误：请提供 offset_days（整数天数）"}
        try:
            offset_days = int(offset_days)
        except (ValueError, TypeError):
            return {"content": "❌ 参数错误：offset_days 必须是整数"}

        set_time_offset_days(offset_days)
        virtual_today = get_virtual_today()
        real_today = date.today()
        msg = (
            f"✅ 设置时间偏移成功\n"
            f"⏱️ 偏移量：{offset_days:+d} 天\n"
            f"📅 真实今天：{real_today.isoformat()}\n"
            f"📅 虚拟今天：{virtual_today.isoformat()}\n"
            f"(后续所有日期计算均使用虚拟今天，包括 /test/trigger_buffer)"
        )
        return {
            "content": msg,
            "offset_days": offset_days,
            "real_today": real_today.isoformat(),
            "virtual_today": virtual_today.isoformat(),
        }
    except Exception as e:
        logging.error(f"设置时间偏移失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}


@app.post("/test/clear_time_offset")
async def test_clear_time_offset():
    """测试接口：清除时间偏移，恢复真实时间"""
    try:
        clear_time_offset_days()
        virtual_today = get_virtual_today()
        real_today = date.today()
        msg = (
            f"✅ 已清除时间偏移\n"
            f"📅 真实今天：{real_today.isoformat()}\n"
            f"📅 虚拟今天：{virtual_today.isoformat()}（现在与真实时间一致）"
        )
        return {
            "content": msg,
            "offset_days": 0,
            "real_today": real_today.isoformat(),
            "virtual_today": virtual_today.isoformat(),
        }
    except Exception as e:
        logging.error(f"清除时间偏移失败: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}


@app.get("/test/get_current_time")
async def test_get_current_time():
    """测试接口：获取当前时间信息（真实时间 + 虚拟时间 + 偏移量）"""
    real_now = datetime.now()
    virtual_now = get_virtual_now()
    offset = get_time_offset_days()
    real_today = real_now.date()
    virtual_today = virtual_now.date()

    # scheduler 下次执行时间
    next_run_info = None
    sched = app.state.scheduler
    if sched:
        try:
            jobs = sched.get_jobs()
            if jobs:
                job = jobs[0]
                if job.next_run_time:
                    next_run_info = job.next_run_time.isoformat()
        except Exception:
            pass

    return {
        "content": (
            f"⏱️ 时间偏移量：{offset:+d} 天\n"
            f"🕒 真实当前时间：{real_now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📅 真实今天：{real_today.isoformat()}\n"
            f"🕒 虚拟当前时间：{virtual_now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📅 虚拟今天：{virtual_today.isoformat()}\n"
            f"🔔 定时任务下次执行（北京时间）：{next_run_info or '调度器未启动'}"
        ),
        "offset_days": offset,
        "real_now": real_now.isoformat(timespec="seconds"),
        "real_today": real_today.isoformat(),
        "virtual_now": virtual_now.isoformat(timespec="seconds"),
        "virtual_today": virtual_today.isoformat(),
        "scheduler_next_run": next_run_info,
    }


@app.post("/test/trigger_buffer")
async def test_trigger_buffer(request: Request):
    """测试接口：手动触发 buffer 管理主流程（立即执行，不等零点）
    执行顺序：1.更新buffer范围 → 2.删除过期离散表 → 3.补新表（255限额检查）

    可选参数（覆盖默认值，便于测试）：
      - days:       buffer 未来几天（默认用 BUFFER_DAYS_FUTURE）
      - past_days:  buffer 过去几天（默认用 BUFFER_PAST_DAYS）

    请求 Body 示例：
      {}                                → 使用默认参数执行
      {"days": 60, "past_days": 3}     → 自定义 buffer 范围
    """
    try:
        body = await request.json() or {}
        days = body.get("days", BUFFER_DAYS_FUTURE)
        past_days = body.get("past_days", BUFFER_PAST_DAYS)
        operator_userid = body.get("operator_userid", "test_trigger")
        operator_name = body.get("operator_name", "测试手动触发")

        logging.info(f"[测试触发] 手动触发 buffer 管理：days={days}, past_days={past_days}")
        result = buffer_manage_and_sync(
            corp_id=CORP_ID,
            secret=SECRET,
            operator_userid=operator_userid,
            operator_name=operator_name,
            days=days,
            sessions=SESSIONS,
            past_days=past_days,
        )

        # 构造友好的汇总消息
        s1 = result["step1_update_buffer_flags"]
        s2 = result["step2_delete_expired"]
        s3 = result["step3_supplement_new"]

        msg_lines = [
            f"✅ buffer 管理执行完成",
            f"📅 虚拟今天：{result['virtual_today']}（偏移 {result['time_offset_days']:+d} 天）",
            f"🎯 buffer 范围：[{s1['buffer_start']}, {s1['buffer_end']}]",
            "",
            f"--- 步骤1：更新 buffer 标记 ---",
            f"  影响行数：{s1['updated_rows']} 行",
            "",
            f"--- 步骤2：删除过期离散工作表（日期<今天 且 is_buffer=0）---",
            f"  查找到过期表：{s2['expired_count']} 张",
            f"  删除成功：{s2['delete_success_count']} 张",
            f"  删除失败：{s2['delete_failed_count']} 张",
        ]
        if s2["delete_success"]:
            names = "、".join(s["sheet_name"] for s in s2["delete_success"][:5])
            msg_lines.append(f"  删除成功（前5张）：{names}")
        if s2["delete_failed"]:
            fail_names = "、".join(s.get("sheet_name", "?") for s in s2["delete_failed"][:5])
            msg_lines.append(f"  删除失败（前5张）：{fail_names}")

        msg_lines += [
            "",
            f"--- 步骤3：补足 buffer 新工作表（限额 {result['max_limit']} 张）---",
            f"  执行前总表数：{result['total_sheets_before']} 张",
            f"  补表成功：{s3.get('created_count', 0)} 张",
            f"  因限额跳过：{s3.get('skipped_count', 0)} 张",
            f"  执行后总表数：{result['total_sheets_after']} 张",
        ]
        if s3.get("created"):
            names = "、".join(s["sheet_name"] for s in s3["created"][:5])
            msg_lines.append(f"  补表成功（前5张）：{names}")
        if s3.get("skipped_due_to_limit"):
            names = "、".join(s["sheet_name"] for s in s3["skipped_due_to_limit"][:5])
            msg_lines.append(f"  因限额跳过（前5张）：{names}")

        return {
            "content": "\n".join(msg_lines),
            **result,
        }
    except Exception as e:
        logging.error(f"手动触发 buffer 管理失败: {e}", exc_info=True)
        return {"content": f"❌ 操作失败: {str(e)}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)