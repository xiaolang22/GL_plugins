import logging
import calendar
from datetime import date, timedelta
from typing import List, Dict, Any
import api_wework
import db

# 星期名称（与 date.weekday() 0=周一 对应）
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 座位数据（按顺序）
SEAT_DATA = [
    ("北京房", 15, "有麻将桌", "房间"),
    ("上海房", 12, "", "房间"),
    ("广州房", 12, "", "房间"),
    ("深圳房", 17, "", "房间"),
    ("佛山房", 20, "有麻将桌", "房间"),
    ("天津房", 12, "", "房间"),
    ("重庆房", 12, "", "房间"),
    ("大连房", 12, "", "房间"),
    ("济南房", 12, "", "房间"),
    ("郑州房", 10, "", "房间"),
    ("长沙房", 10, "", "房间"),
    ("1号桌", 8, "", "大厅"),
    ("2号桌", 12, "头顶有空调", "大厅"),
    ("3号桌", 12, "头顶有空调", "大厅"),
    ("5号桌", 13, "", "大厅"),
    ("6号桌", 20, "", "大厅"),
    ("7号桌", 8, "", "大厅"),
    ("8号桌", 12, "", "大厅"),
    ("9号桌", 8, "", "大厅"),
    ("10号桌", 8, "", "大厅"),
    ("11号桌", 8, "", "大厅"),
    ("12号桌", 12, "", "大厅"),
    ("13号桌", 12, "", "大厅"),
    ("15号桌", 12, "", "大厅"),
    ("16号桌", 12, "", "大厅"),
    ("17号桌", 12, "", "大厅"),
    ("18号桌", 12, "", "大厅"),
    ("19号桌", 12, "", "大厅"),
    ("20号桌", 15, "头顶有空调", "大厅"),
    ("21号桌", 8, "", "大厅"),
    ("22号桌", 12, "窗边", "大厅"),
    ("23号桌", 12, "窗边", "大厅"),
    ("25号桌", 12, "窗边", "大厅"),
    ("26号桌", 12, "窗边", "大厅"),
    ("27号桌", 15, "窗边", "大厅"),
    ("28号桌", 4, "", "大厅"),
    ("29号桌", 4, "", "大厅"),
    ("加29号桌", 4, "", "大厅"),
    ("30号桌", 4, "", "大厅"),
    ("31号桌", 4, "", "大厅"),
    ("32号桌", 8, "窗边", "大厅"),
    ("33号桌", 4, "窗边", "大厅"),
    ("35号桌", 4, "窗边", "大厅"),
    ("36号桌", 8, "窗边", "大厅"),
    ("37号桌", 8, "窗边", "大厅"),
    ("38号桌", 4, "窗边", "大厅"),
]

def create_smart_sheet_and_sync(corp_id: str, secret: str, doc_name: str, admin_users: List[str], operator_userid: str, operator_name: str) -> Dict[str, Any]:
    """
    复合操作1：创建智能表格并同步到数据库
    返回: {"doc_id": "...", "doc_url": "...", "db_id": ...}
    """
    token = api_wework.get_access_token(corp_id, secret)
    result = api_wework.create_doc(token, doc_name, admin_users)
    doc_id = result["docid"]
    doc_url = result["url"]

    # 插入数据库
    db_id = db.insert_doc(doc_id, doc_name, doc_url, operator_userid)

    # 记录日志（先插入操作人）
    user_id = db.insert_user(operator_userid, operator_name)
    db.insert_log(
        operator_id=user_id,
        target_id=db_id,
        operation_type="create_doc",
        target_type="doc",
        detail={"doc_name": doc_name, "doc_id": doc_id}
    )

    return {"doc_id": doc_id, "doc_url": doc_url, "db_id": db_id}

def create_template_sheet_and_sync(corp_id: str, secret: str, template_name: str, operator_userid: str, operator_name: str) -> Dict[str, Any]:
    """
    复合操作2：在第一个智能表格中创建模板工作表，添加字段和记录，同步数据库
    返回: {"sheet_id": "...", "template_db_id": ...}
    """
    # 获取第一个智能表格的 doc_id
    doc_id = db.get_first_doc()
    if not doc_id:
        raise Exception("没有找到已存在的智能表格，请先创建智能表格")

    token = api_wework.get_access_token(corp_id, secret)

    # 1. 添加子表
    sheet_result = api_wework.add_sheet(token, doc_id, template_name)
    sheet_id = sheet_result["properties"]["sheet_id"]

    # 1.5 将子表自带的默认字段重命名为第一个字段"座位名称"
    # （add_sheet 会自动创建一个默认文本字段，子表至少需保留一个字段，不能直接删除）
    existing_fields = api_wework.get_fields(token, doc_id, sheet_id)
    default_fields = existing_fields.get("fields", [])
    if default_fields:
        default_field_id = default_fields[0]["field_id"]
        api_wework.update_fields(token, doc_id, sheet_id, [{
            "field_id": default_field_id,
            "field_title": "座位名称",
            "field_type": "FIELD_TYPE_TEXT"
        }])

    # 2. 添加剩余 9 个字段（"座位名称"已通过重命名默认字段获得，保持第一列）
    # 需求从左到右顺序：座位名称(已有)、座位容量、座位备注、客人称呼、客人电话、人数、留菜、留位人、座位类型、是否已订
    # 注意：add_fields 会将新字段**前置插入**（插入到最左侧），因此需要按逆序传入，才能得到正确从左到右顺序
    fields = [
        {
            "field_title": "是否已订",
            "field_type": "FIELD_TYPE_SINGLE_SELECT",
            "property_single_select": {
                "options": [{"text": "已订座"}, {"text": "未订座"}]
            }
        },
        {
            "field_title": "座位类型",
            "field_type": "FIELD_TYPE_SINGLE_SELECT",
            "property_single_select": {
                "options": [{"text": "房间"}, {"text": "大厅"}]
            }
        },
        {"field_title": "留位人", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "留菜", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "人数", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "客人电话", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "客人称呼", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "座位备注", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "座位容量", "field_type": "FIELD_TYPE_TEXT"},
    ]
    api_wework.add_fields(token, doc_id, sheet_id, fields)

    # 3. 添加记录
    # 文本字段值需为 [{"type": "text", "text": "..."}]，单选字段值需为 [{"text": "..."}]
    def text_value(s):
        return [{"type": "text", "text": str(s)}]

    def select_value(s):
        return [{"text": str(s)}]

    records = []
    for name, capacity, remark, seat_type in SEAT_DATA:
        records.append({
            "values": {
                "座位名称": text_value(name),
                "座位容量": text_value(capacity),
                "座位备注": text_value(remark),
                "座位类型": select_value(seat_type),
                "是否已订": select_value("未订座")
            }
        })
    api_wework.add_records(token, doc_id, sheet_id, records)

    # 4. 设置分组规则：1.按是否已订选项正序；2.按座位类型选项正序
    # 需要先获取"座位类型"和"是否已订"字段的 field_id，以及默认视图的 view_id
    all_fields = api_wework.get_fields(token, doc_id, sheet_id)
    field_id_map = {f["field_title"]: f["field_id"] for f in all_fields.get("fields", [])}
    seat_type_field_id = field_id_map.get("座位类型")
    is_booked_field_id = field_id_map.get("是否已订")

    views_result = api_wework.get_views(token, doc_id, sheet_id)
    views = views_result.get("views", [])
    if views and seat_type_field_id and is_booked_field_id:
        default_view_id = views[0]["view_id"]
        api_wework.update_view(token, doc_id, sheet_id, default_view_id, {
            "group_spec": {
                "groups": [
                    {"field_id": is_booked_field_id, "desc": False},
                    {"field_id": seat_type_field_id, "desc": False}
                ]
            }
        })

    # 5. 构造模板内容 JSON（与实际创建的模板结构一致，便于后续复用）
    # 5.1 字段定义（按从左到右顺序）
    template_fields = [
        {"field_title": "座位名称", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "座位容量", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "座位备注", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "客人称呼", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "客人电话", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "人数", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "留菜", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "留位人", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "座位类型", "field_type": "FIELD_TYPE_SINGLE_SELECT", "options": ["房间", "大厅"]},
        {"field_title": "是否已订", "field_type": "FIELD_TYPE_SINGLE_SELECT", "options": ["已订座", "未订座"]},
    ]

    # 5.2 记录数据（使用可读格式，而非 API 特定的 value 封装格式）
    template_records = []
    for name, capacity, remark, seat_type in SEAT_DATA:
        template_records.append({
            "座位名称": name,
            "座位容量": str(capacity),
            "座位备注": remark,
            "客人称呼": "",
            "客人电话": "",
            "人数": "",
            "留菜": "",
            "留位人": "",
            "座位类型": seat_type,
            "是否已订": "未订座"
        })

    # 5.3 分组规则（使用字段标题而非动态 field_id，便于跨实例复用）
    template_group_spec = {
        "groups": [
            {"field_title": "是否已订", "desc": False},
            {"field_title": "座位类型", "desc": False}
        ]
    }

    template_content = {
        "fields": template_fields,
        "records": template_records,
        "group_spec": template_group_spec
    }

    # 6. 同步数据库：插入模板记录（含 template_content）
    template_db_id = db.insert_template(doc_id, sheet_id, template_name, operator_userid, template_content)

    # 7. 日志
    user_id = db.insert_user(operator_userid, operator_name)
    db.insert_log(
        operator_id=user_id,
        target_id=template_db_id,
        operation_type="create_template",
        target_type="template",
        detail={"template_name": template_name, "sheet_id": sheet_id}
    )

    return {"sheet_id": sheet_id, "template_db_id": template_db_id}


def _add_months(d: date, months: int) -> date:
    """日期加几个月，自动处理月末溢出（如 1月31日 + 1月 = 2月28/29日）"""
    month = d.month - 1 + months  # 转为 0-indexed 计算
    year = d.year + month // 12
    month = month % 12 + 1  # 转回 1-indexed
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def _build_field_payload(field_def: Dict) -> Dict:
    """把 template_content 中的字段定义转为 add_fields 的 payload 格式"""
    payload = {"field_title": field_def["field_title"], "field_type": field_def["field_type"]}
    if field_def["field_type"] == "FIELD_TYPE_SINGLE_SELECT":
        payload["property_single_select"] = {
            "options": [{"text": opt} for opt in field_def.get("options", [])]
        }
    return payload


def _build_record_payload(record: Dict, fields_def: List[Dict]) -> Dict:
    """把 template_content 中的记录转为 add_records 的 payload 格式"""
    values = {}
    for field_def in fields_def:
        title = field_def["field_title"]
        value = record.get(title, "")
        if field_def["field_type"] == "FIELD_TYPE_SINGLE_SELECT":
            values[title] = [{"text": str(value)}]
        else:
            values[title] = [{"type": "text", "text": str(value)}]
    return {"values": values}


def _create_one_sheet_from_template(token: str, doc_id: str, sheet_name: str, template_content: Dict) -> str:
    """按模板内容创建一张工作表，返回 sheet_id"""
    fields_def = template_content["fields"]

    # 1. 添加子表
    sheet_result = api_wework.add_sheet(token, doc_id, sheet_name)
    sheet_id = sheet_result["properties"]["sheet_id"]

    # 2. 重命名子表自带的默认字段为第一个字段（add_sheet 会自动创建一个默认文本字段）
    first_field = fields_def[0]
    existing_fields = api_wework.get_fields(token, doc_id, sheet_id)
    default_fields = existing_fields.get("fields", [])
    if default_fields:
        default_field_id = default_fields[0]["field_id"]
        api_wework.update_fields(token, doc_id, sheet_id, [{
            "field_id": default_field_id,
            "field_title": first_field["field_title"],
            "field_type": first_field["field_type"]
        }])

    # 3. 添加剩余字段（逆序传入，因为 add_fields 会将新字段前置插入）
    rest_fields = [_build_field_payload(f) for f in reversed(fields_def[1:])]
    if rest_fields:
        api_wework.add_fields(token, doc_id, sheet_id, rest_fields)

    # 4. 添加记录
    records = [_build_record_payload(rec, fields_def) for rec in template_content.get("records", [])]
    if records:
        api_wework.add_records(token, doc_id, sheet_id, records)

    # 5. 设置分组规则（template_content 中用 field_title 标识，需动态解析为 field_id）
    group_spec = template_content.get("group_spec", {})
    groups_def = group_spec.get("groups", [])
    if groups_def:
        all_fields = api_wework.get_fields(token, doc_id, sheet_id)
        field_id_map = {f["field_title"]: f["field_id"] for f in all_fields.get("fields", [])}
        views_result = api_wework.get_views(token, doc_id, sheet_id)
        views = views_result.get("views", [])
        if views:
            view_id = views[0]["view_id"]
            groups = []
            for g in groups_def:
                fid = field_id_map.get(g["field_title"])
                if fid:
                    groups.append({"field_id": fid, "desc": g.get("desc", False)})
            if groups:
                api_wework.update_view(token, doc_id, sheet_id, view_id, {
                    "group_spec": {"groups": groups}
                })

    return sheet_id


def create_bulk_sheets_and_sync(corp_id: str, secret: str, operator_userid: str, operator_name: str,
                                 months: int = 3, sessions: List[tuple] = None) -> Dict[str, Any]:
    """
    复合操作3：批量新建工作表（从今天起未来 months 个月）
    - 模板内容从数据库读取（templates.template_content）
    - 一天创建多张工作表（默认午市+晚市）
    - 命名规则：{月}-{日}{午市/晚市}{星期}，如 "9-26晚市周六"
    - 同步到 sheets 表
    返回: {"success_count": ..., "failed_count": ..., ...}
    """
    if sessions is None:
        sessions = [("lunch", "午市"), ("dinner", "晚市")]

    # 1. 获取第一个智能表格
    doc_id = db.get_first_doc()
    if not doc_id:
        raise Exception("没有找到已存在的智能表格，请先创建智能表格")

    # 2. 获取第一个模板（含 template_content）
    template = db.get_first_template()
    if not template:
        raise Exception("没有找到已存在的模板工作表，请先创建模板")
    template_content = template.get("template_content")
    template_id = template["id"]
    if not template_content:
        raise Exception("模板内容为空，无法复刻工作表")

    token = api_wework.get_access_token(corp_id, secret)

    # 3. 计算日期范围（从今天到三个月后的同一天前一天，与需求示例一致：6月1日 → 8月31日）
    start_date = date.today()
    end_date = _add_months(start_date, months) - timedelta(days=1)

    # 4. 遍历每一天，每天按 sessions 创建工作表
    total_days = (end_date - start_date).days + 1
    total_sheets = total_days * len(sessions)

    success_count = 0
    failed_sheets = []
    created_sheets = []

    user_id = db.insert_user(operator_userid, operator_name)

    current = start_date
    sheet_index = 0
    while current <= end_date:
        weekday_name = WEEKDAYS[current.weekday()]
        for session_type, session_name in sessions:
            sheet_name = f"{current.month}-{current.day}{session_name}{weekday_name}"
            sheet_index += 1
            try:
                logging.info(f"[{sheet_index}/{total_sheets}] 创建工作表: {sheet_name}")
                sheet_id = _create_one_sheet_from_template(token, doc_id, sheet_name, template_content)

                # 同步数据库
                db.insert_sheet(
                    doc_id=doc_id,
                    sheet_id=sheet_id,
                    sheet_name=sheet_name,
                    sheet_date=current.isoformat(),
                    session_type=session_type,
                    weekday=weekday_name,
                    template_id=template_id,
                    created_by=operator_userid
                )
                created_sheets.append({"sheet_name": sheet_name, "sheet_id": sheet_id})
                success_count += 1
            except Exception as e:
                logging.error(f"创建工作表 {sheet_name} 失败: {e}")
                failed_sheets.append({"sheet_name": sheet_name, "error": str(e)})
                db.insert_log(
                    operator_id=user_id,
                    target_id=template_id,
                    operation_type="create_bulk_sheets",
                    target_type="sheet",
                    detail={"sheet_name": sheet_name, "sheet_date": current.isoformat()},
                    error_msg=str(e)
                )
        current += timedelta(days=1)

    # 5. 汇总日志
    db.insert_log(
        operator_id=user_id,
        target_id=template_id,
        operation_type="create_bulk_sheets",
        target_type="sheet",
        detail={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total": total_sheets,
            "success": success_count,
            "failed": len(failed_sheets)
        }
    )

    return {
        "success_count": success_count,
        "failed_count": len(failed_sheets),
        "failed_sheets": failed_sheets,
        "created_sheets": created_sheets,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    }