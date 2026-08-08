import logging
import calendar
import httpx
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    with httpx.Client(timeout=30) as client:
        token = api_wework.get_access_token(client, corp_id, secret)
        result = api_wework.create_doc(client, token, doc_name, admin_users)
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

    with httpx.Client(timeout=30) as client:
        token = api_wework.get_access_token(client, corp_id, secret)

        # 1. 添加子表
        sheet_result = api_wework.add_sheet(client, token, doc_id, template_name)
        sheet_id = sheet_result["properties"]["sheet_id"]

        # 1.5 将子表自带的默认字段重命名为第一个字段"座位名称"
        # （add_sheet 会自动创建一个默认文本字段，子表至少需保留一个字段，不能直接删除）
        existing_fields = api_wework.get_fields(client, token, doc_id, sheet_id)
        default_fields = existing_fields.get("fields", [])
        if default_fields:
            default_field_id = default_fields[0]["field_id"]
            api_wework.update_fields(client, token, doc_id, sheet_id, [{
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
        api_wework.add_fields(client, token, doc_id, sheet_id, fields)

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
        api_wework.add_records(client, token, doc_id, sheet_id, records)

        # 4. 设置分组规则：1.按是否已订选项正序；2.按座位类型选项正序
        # 需要先获取"座位类型"和"是否已订"字段的 field_id，以及默认视图的 view_id
        all_fields = api_wework.get_fields(client, token, doc_id, sheet_id)
        field_id_map = {f["field_title"]: f["field_id"] for f in all_fields.get("fields", [])}
        seat_type_field_id = field_id_map.get("座位类型")
        is_booked_field_id = field_id_map.get("是否已订")

        views_result = api_wework.get_views(client, token, doc_id, sheet_id)
        views = views_result.get("views", [])
        if views and seat_type_field_id and is_booked_field_id:
            default_view_id = views[0]["view_id"]
            api_wework.update_view(client, token, doc_id, sheet_id, default_view_id, {
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


def _fill_sheet_from_template(client: httpx.Client, token: str, doc_id: str, sheet_id: str, template_content: Dict) -> None:
    """填充子表（幂等）：重命名默认字段 → 添加缺失字段 → 添加记录 → 设置分组规则

    幂等性设计（用于阶段三重试场景，避免重复添加）：
    - 字段：按 field_title 去重，只添加缺失的字段
    - 记录：先查询记录数，仅在无记录时添加
    - 分组规则：update_view 本身是覆盖写入，天然幂等
    """
    fields_def = template_content["fields"]
    first_field = fields_def[0]

    # 1. 检查现有字段，判断哪些步骤需要执行
    existing_fields_resp = api_wework.get_fields(client, token, doc_id, sheet_id)
    existing_fields = existing_fields_resp.get("fields", [])
    existing_titles = {f["field_title"] for f in existing_fields}

    # 1a. 重命名默认字段（如果第一个字段标题尚不存在，说明默认字段还未被重命名）
    if first_field["field_title"] not in existing_titles and existing_fields:
        default_field_id = existing_fields[0]["field_id"]
        api_wework.update_fields(client, token, doc_id, sheet_id, [{
            "field_id": default_field_id,
            "field_title": first_field["field_title"],
            "field_type": first_field["field_type"]
        }])
        existing_titles.add(first_field["field_title"])

    # 2. 添加缺失的字段（逆序传入，因为 add_fields 会将新字段前置插入）
    missing_fields = [f for f in fields_def[1:] if f["field_title"] not in existing_titles]
    if missing_fields:
        rest_payload = [_build_field_payload(f) for f in reversed(missing_fields)]
        api_wework.add_fields(client, token, doc_id, sheet_id, rest_payload)

    # 3. 添加记录（仅在无记录时添加，保证幂等）
    records_resp = api_wework.get_records(client, token, doc_id, sheet_id, limit=1)
    existing_count = records_resp.get("total", len(records_resp.get("records", [])))
    if existing_count == 0:
        records = [_build_record_payload(rec, fields_def) for rec in template_content.get("records", [])]
        if records:
            api_wework.add_records(client, token, doc_id, sheet_id, records)

    # 4. 设置分组规则（覆盖写入，天然幂等）
    group_spec = template_content.get("group_spec", {})
    groups_def = group_spec.get("groups", [])
    if groups_def:
        all_fields_resp = api_wework.get_fields(client, token, doc_id, sheet_id)
        field_id_map = {f["field_title"]: f["field_id"] for f in all_fields_resp.get("fields", [])}
        views_result = api_wework.get_views(client, token, doc_id, sheet_id)
        views = views_result.get("views", [])
        if views:
            view_id = views[0]["view_id"]
            groups = []
            for g in groups_def:
                fid = field_id_map.get(g["field_title"])
                if fid:
                    groups.append({"field_id": fid, "desc": g.get("desc", False)})
            if groups:
                api_wework.update_view(client, token, doc_id, sheet_id, view_id, {
                    "group_spec": {"groups": groups}
                })


def _create_one_sheet_from_template(client: httpx.Client, token: str, doc_id: str, sheet_name: str, template_content: Dict) -> str:
    """按模板内容创建一张工作表（串行版，供单张创建场景使用），返回 sheet_id"""
    sheet_result = api_wework.add_sheet(client, token, doc_id, sheet_name)
    sheet_id = sheet_result["properties"]["sheet_id"]
    _fill_sheet_from_template(client, token, doc_id, sheet_id, template_content)
    return sheet_id


def create_bulk_sheets_and_sync(corp_id: str, secret: str, operator_userid: str, operator_name: str,
                                 months: int = 3, sessions: List[tuple] = None,
                                 max_workers: int = 5) -> Dict[str, Any]:
    """
    复合操作3：批量新建工作表（从今天起未来 months 个月），三阶段流水线加速
    - 模板内容从数据库读取（templates.template_content）
    - 一天创建多张工作表（默认午市+晚市）
    - 命名规则：{月}-{日}{午市/晚市}{星期}，如 "9-26晚市周六"

    三阶段流水线：
    - 阶段一：串行创建子表（add_sheet），保证子表按日期顺序排列
    - 阶段二：并发填充（字段/记录/分组规则），默认 max_workers 路并发
    - 阶段三：针对阶段二填充失败的工作表，串行重试

    返回: {
        "total": ..., "start_date": ..., "end_date": ...,
        "phase1_failed_count": ...,      # 阶段一失败（子表都没建出来）
        "phase2_success_count": ...,     # 阶段二直接成功
        "phase3_retry_success_count": ...,# 阶段三重试成功
        "phase3_retry_failed_count": ..., # 阶段三重试仍失败
        "final_success_count": ...,       # phase2_success + phase3_retry_success
        "final_failed_count": ...,        # phase1_failed + phase3_retry_failed
        "phase1_failed": [...],
        "phase3_retry_success": [...],
        "phase3_retry_failed": [...],
    }
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

    with httpx.Client(timeout=30) as client:
        token = api_wework.get_access_token(client, corp_id, secret)

        # 3. 计算日期范围（从今天到 months 个月后的同一天前一天，与需求示例一致：6月1日 → 8月31日）
        start_date = date.today()
        end_date = _add_months(start_date, months) - timedelta(days=1)

        # 4. 构建任务列表（按日期顺序排列，确保阶段一串行创建的子表顺序正确）
        tasks = []  # 每项: {"sheet_name", "sheet_date", "session_type", "weekday"}
        current = start_date
        while current <= end_date:
            weekday_name = WEEKDAYS[current.weekday()]
            for session_type, session_name in sessions:
                sheet_name = f"{current.month}-{current.day}{session_name}{weekday_name}"
                tasks.append({
                    "sheet_name": sheet_name,
                    "sheet_date": current.isoformat(),
                    "session_type": session_type,
                    "weekday": weekday_name,
                })
            current += timedelta(days=1)

        total = len(tasks)
        user_id = db.insert_user(operator_userid, operator_name)
        logging.info(f"批量创建工作表：{start_date} ~ {end_date}，共 {total} 张，并发数 {max_workers}")

        # ==================== 阶段一：串行创建子表 ====================
        # 串行调用 add_sheet，保证子表在企业微信文档中按日期顺序排列
        logging.info(f"===== 阶段一：串行创建子表（{total} 张）=====")
        phase1_created = []  # 成功创建子表的任务: [(task, sheet_id), ...]
        phase1_failed = []   # 阶段一失败的任务: [(task, error), ...]
        for i, task in enumerate(tasks, 1):
            try:
                logging.info(f"[1-{i}/{total}] 创建子表: {task['sheet_name']}")
                sheet_result = api_wework.add_sheet(client, token, doc_id, task["sheet_name"])
                sheet_id = sheet_result["properties"]["sheet_id"]
                phase1_created.append((task, sheet_id))
            except Exception as e:
                logging.error(f"[1-{i}/{total}] 创建子表失败 {task['sheet_name']}: {e}")
                phase1_failed.append((task, str(e)))

        logging.info(f"阶段一完成：成功 {len(phase1_created)} 张，失败 {len(phase1_failed)} 张")

        # ==================== 阶段二：并发填充 ====================
        # 对阶段一成功的子表，并发执行 _fill_sheet_from_template（字段/记录/分组规则）
        # 共享 client 是线程安全的，连接池自动管理并发连接
        to_fill_count = len(phase1_created)
        logging.info(f"===== 阶段二：并发填充（{to_fill_count} 张，{max_workers} 路并发）=====")

        def _fill_worker(task: Dict, sheet_id: str) -> Dict:
            """并发填充 worker：仅做 API 调用，返回结果由主线程统一处理 DB"""
            try:
                _fill_sheet_from_template(client, token, doc_id, sheet_id, template_content)
                return {"task": task, "sheet_id": sheet_id, "error": None}
            except Exception as e:
                return {"task": task, "sheet_id": sheet_id, "error": str(e)}

        phase2_success = []   # 阶段二直接成功: [(task, sheet_id), ...]
        phase2_failed = []    # 阶段二失败（待重试）: [(task, sheet_id), ...]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_fill_worker, task, sid): (task, sid)
                for task, sid in phase1_created
            }
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                task = result["task"]
                sheet_id = result["sheet_id"]
                err = result["error"]
                if err:
                    logging.error(f"[2-{i}/{to_fill_count}] 填充失败 {task['sheet_name']}: {err}")
                    phase2_failed.append((task, sheet_id, err))
                else:
                    logging.info(f"[2-{i}/{to_fill_count}] 填充成功 {task['sheet_name']}")
                    phase2_success.append((task, sheet_id))

        logging.info(f"阶段二完成：成功 {len(phase2_success)} 张，失败 {len(phase2_failed)} 张（待重试）")

        # ==================== 阶段三：串行重试 ====================
        # 对阶段二失败的工作表，串行重试填充（_fill_sheet_from_template 是幂等的，可安全重试）
        retry_count = len(phase2_failed)
        logging.info(f"===== 阶段三：串行重试（{retry_count} 张）=====")
        phase3_success = []  # 重试成功: [(task, sheet_id), ...]
        phase3_failed = []   # 重试仍失败: [(task, sheet_id, error), ...]
        for i, (task, sheet_id, _) in enumerate(phase2_failed, 1):
            try:
                logging.info(f"[3-{i}/{retry_count}] 重试填充: {task['sheet_name']}")
                _fill_sheet_from_template(client, token, doc_id, sheet_id, template_content)
                phase3_success.append((task, sheet_id))
            except Exception as e:
                logging.error(f"[3-{i}/{retry_count}] 重试失败 {task['sheet_name']}: {e}")
                phase3_failed.append((task, sheet_id, str(e)))

        logging.info(f"阶段三完成：重试成功 {len(phase3_success)} 张，重试失败 {len(phase3_failed)} 张")

    # ==================== 同步数据库 ====================
    # 对所有最终成功的子表，写入 sheets 表（主线程串行写，避免 SQLite 并发问题）
    all_success = phase2_success + phase3_success
    for task, sheet_id in all_success:
        db.insert_sheet(
            doc_id=doc_id,
            sheet_id=sheet_id,
            sheet_name=task["sheet_name"],
            sheet_date=task["sheet_date"],
            session_type=task["session_type"],
            weekday=task["weekday"],
            template_id=template_id,
            created_by=operator_userid
        )

    # 记录失败日志（阶段一失败 + 阶段三重试失败）
    all_failures = []
    for task, err in phase1_failed:
        all_failures.append({"sheet_name": task["sheet_name"], "phase": "phase1", "error": err})
        db.insert_log(
            operator_id=user_id,
            target_id=template_id,
            operation_type="create_bulk_sheets",
            target_type="sheet",
            detail={"sheet_name": task["sheet_name"], "sheet_date": task["sheet_date"], "phase": "phase1"},
            error_msg=err
        )
    for task, sheet_id, err in phase3_failed:
        all_failures.append({"sheet_name": task["sheet_name"], "phase": "phase3", "error": err})
        db.insert_log(
            operator_id=user_id,
            target_id=template_id,
            operation_type="create_bulk_sheets",
            target_type="sheet",
            detail={"sheet_name": task["sheet_name"], "sheet_date": task["sheet_date"], "phase": "phase3"},
            error_msg=err
        )

    # 汇总日志
    final_success = len(all_success)
    final_failed = len(all_failures)
    db.insert_log(
        operator_id=user_id,
        target_id=template_id,
        operation_type="create_bulk_sheets",
        target_type="sheet",
        detail={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total": total,
            "phase1_failed": len(phase1_failed),
            "phase2_success": len(phase2_success),
            "phase3_retry_success": len(phase3_success),
            "phase3_retry_failed": len(phase3_failed),
            "final_success": final_success,
            "final_failed": final_failed,
            "max_workers": max_workers,
        }
    )

    logging.info(f"===== 批量创建完成 =====")
    logging.info(f"最终结果：成功 {final_success} 张，失败 {final_failed} 张")
    logging.info(f"  阶段一直接成功（子表创建）: {len(phase1_created)} 张")
    logging.info(f"  阶段二并发填充成功: {len(phase2_success)} 张")
    logging.info(f"  阶段三重试成功: {len(phase3_success)} 张")
    logging.info(f"  阶段一失败: {len(phase1_failed)} 张")
    logging.info(f"  阶段三重试失败: {len(phase3_failed)} 张")

    return {
        "total": total,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "max_workers": max_workers,
        # 分阶段统计
        "phase1_failed_count": len(phase1_failed),
        "phase2_success_count": len(phase2_success),
        "phase3_retry_success_count": len(phase3_success),
        "phase3_retry_failed_count": len(phase3_failed),
        # 最终统计
        "final_success_count": final_success,
        "final_failed_count": final_failed,
        # 明细
        "phase1_failed": [{"sheet_name": t["sheet_name"], "error": e} for t, e in phase1_failed],
        "phase3_retry_success": [{"sheet_name": t["sheet_name"]} for t, _sid in phase3_success],
        "phase3_retry_failed": [{"sheet_name": t["sheet_name"], "error": e} for t, _sid, e in phase3_failed],
    }


# ============================================================
# 工具4：按任意日期 + 场次新建工作表（单张入口，外部可访问）
# ============================================================
def _parse_date_str(date_str: str) -> date:
    """解析日期字符串，支持 'YYYY-MM-DD' / 'YYYY/MM/DD' / 'MM-DD' / 'MM/DD'"""
    if not date_str:
        raise ValueError("date 参数不能为空")
    s = date_str.strip().replace("/", "-")
    parts = s.split("-")
    if len(parts) == 3:
        y, m, d = (int(p) for p in parts)
    elif len(parts) == 2:
        m, d = (int(p) for p in parts)
        y = date.today().year
    else:
        raise ValueError(f"无法解析日期 '{date_str}'，请使用 YYYY-MM-DD 或 MM-DD 格式")
    try:
        return date(y, m, d)
    except ValueError as e:
        raise ValueError(f"日期不合法 '{date_str}': {e}")


def _make_sheet_name(target: date, session_label: str) -> str:
    """生成工作表名称：'{月}-{日}{午市/晚市}{星期}'，示例：'9-26晚市周六'"""
    return f"{target.month}-{target.day}{session_label}{WEEKDAYS[target.weekday()]}"


def _normalize_sessions(raw_sessions: Optional[List], default_sessions: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """把 sessions 参数标准化为 [(session_type, label), ...] 列表

    支持输入：
        None 或 "all" 或 空串 → 默认为 default_sessions
        ["lunch", "dinner"] → 按 type 从 default_sessions 里匹配
        [{"session_type": "lunch", "label": "午市"}, ...] → 完整结构
        单个字符串 "lunch" / "午市" → 先匹配 type，再匹配 label
    """
    if raw_sessions is None or raw_sessions == "" or raw_sessions == "all":
        return list(default_sessions)

    # 允许单个值：字符串 or 单场 dict
    if isinstance(raw_sessions, str):
        raw_sessions = [raw_sessions]

    result = []
    known_types = {t for t, _l in default_sessions}
    known_labels = {l: t for t, l in default_sessions}

    for item in raw_sessions:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            result.append((str(item[0]), str(item[1])))
            continue
        if isinstance(item, dict):
            stype = item.get("session_type") or item.get("type")
            slabel = item.get("label") or item.get("name") or item.get("session_label")
            if stype and slabel:
                result.append((stype, slabel))
                continue
            if stype:
                # 找默认 label
                for t, l in default_sessions:
                    if t == stype:
                        result.append((t, l))
                        break
                continue
            if slabel:
                for t, l in default_sessions:
                    if l == slabel:
                        result.append((t, l))
                        break
                continue
            raise ValueError(f"sessions 项格式不合法: {item}")
        if isinstance(item, str):
            # 先匹配 session_type，再匹配中文 label
            s = item.strip()
            if s in known_types:
                for t, l in default_sessions:
                    if t == s:
                        result.append((t, l))
                        break
            elif s in known_labels:
                result.append((known_labels[s], s))
            else:
                raise ValueError(f"未知的 sessions 值: '{s}'，有效值为: {[t for t, _l in default_sessions]} 或 {[l for _t, l in default_sessions]}")
        else:
            raise ValueError(f"sessions 项格式不合法: {item!r}（类型 {type(item).__name__}）")

    if not result:
        raise ValueError("sessions 为空，请至少指定一个场次")

    # 去重（保留首次顺序）
    seen = set()
    unique = []
    for t, l in result:
        if t not in seen:
            seen.add(t)
            unique.append((t, l))
    return unique


def create_any_sheet_and_sync(
    corp_id: str,
    secret: str,
    operator_userid: str,
    operator_name: str,
    sheet_date: str,
    sessions: Optional[List] = None,
    default_sessions: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """在第一个智能表格中，按任意日期 + 场次新建工作表（默认午市+晚市）

    校验逻辑（按需求）：
      1. 不允许与现有表命名重复 → 任一 sheet_name 存在时立即报错，不创建任何表
      2. 不允许新建当前日期之前的工作表 → sheet_date < today 立即报错

    参数:
        corp_id, secret:  企业微信凭证
        operator_userid, operator_name: 操作人
        sheet_date:  目标日期字符串，支持 YYYY-MM-DD / MM-DD
        sessions:    场次列表，支持多种格式（见 _normalize_sessions），None=default_sessions
        default_sessions: 场次的默认配置，示例 [("lunch","午市"), ("dinner","晚市")]

    返回: {
        "created_count": int,
        "skipped_count": int,
        "date": "YYYY-MM-DD",
        "weekday": "周X",
        "sheets": [{"sheet_name": str, "sheet_id": str, "session_type": str, "status": str}]
    }
    """
    if default_sessions is None:
        default_sessions = [("lunch", "午市"), ("dinner", "晚市")]

    # ---------- 步骤 0：前置校验 ----------
    target_date = _parse_date_str(sheet_date)
    today = date.today()

    # 校验 1：不允许新建当前日期之前的工作表
    if target_date < today:
        raise ValueError(
            f"不允许新建过去日期的工作表：目标 {target_date.isoformat()} < 今日 {today.isoformat()}"
        )

    # 解析 sessions
    normalized_sessions = _normalize_sessions(sessions, default_sessions)

    # 预生成所有 sheet_name
    planned_names = [
        _make_sheet_name(target_date, label)
        for _t, label in normalized_sessions
    ]

    # 校验 2：批量查重（命中任一即报错，确保不局部创建）
    existing = db.get_existing_sheet_names(planned_names)
    if existing:
        raise ValueError(
            f"不允许重复创建：以下工作表名称已存在 -> "
            + "、".join(existing)
        )

    # ---------- 步骤 0.5：获取依赖数据 ----------
    doc_id = db.get_first_doc()
    if not doc_id:
        raise Exception("数据库中还没有智能表格，请先调用 /create_doc 创建")
    template = db.get_first_template()
    if not template:
        raise Exception("数据库中还没有模板工作表，请先调用 /create_template 创建")
    template_content = template.get("template_content")
    if not template_content:
        raise Exception("模板工作表内容为空（template_content 未写入），请重新创建模板")
    template_id = template["id"]

    user_id = db.insert_user(operator_userid, operator_name)

    # ---------- 步骤 1：串行创建 + 填充（单张量级，无需并发）----------
    weekday = WEEKDAYS[target_date.weekday()]
    date_iso = target_date.isoformat()
    sheet_results = []

    with httpx.Client(timeout=30) as client:
        token = api_wework.get_access_token(client, corp_id, secret)

        for (session_type, session_label), sheet_name in zip(normalized_sessions, planned_names):
            # 1a. 创建子表
            add_result = api_wework.add_sheet(client, token, doc_id, sheet_name)
            sheet_id = add_result["properties"]["sheet_id"]

            # 1b. 复用填充函数：字段/记录/分组规则
            _fill_sheet_from_template(client, token, doc_id, sheet_id, template_content)

            # 1c. 同步数据库
            db.insert_sheet(
                doc_id=doc_id,
                sheet_id=sheet_id,
                sheet_name=sheet_name,
                sheet_date=date_iso,
                session_type=session_type,
                weekday=weekday,
                template_id=template_id,
                created_by=operator_userid,
            )

            sheet_results.append({
                "sheet_name": sheet_name,
                "sheet_id": sheet_id,
                "session_type": session_type,
                "status": "created",
            })
            logging.info(f"新建工作表成功: {sheet_name}")

    # ---------- 步骤 2：操作日志 ----------
    detail = {
        "date": date_iso,
        "weekday": weekday,
        "created_count": len(sheet_results),
        "sessions": [
            {"session_type": s["session_type"], "sheet_name": s["sheet_name"], "sheet_id": s["sheet_id"]}
            for s in sheet_results
        ],
    }
    target_id_for_log = sheet_results[0]["sheet_name"] if sheet_results else date_iso
    try:
        # target_id 是整数：这里优先取首张工作表 DB id 作为代表，否则 0
        if sheet_results:
            last = db.get_sheets_by_date(date_iso, doc_id)
            if last:
                target_id_for_log = last[-1]["id"]
            else:
                target_id_for_log = 0
        else:
            target_id_for_log = 0
    except Exception:
        target_id_for_log = 0

    db.insert_log(
        operator_id=user_id,
        target_id=int(target_id_for_log) if isinstance(target_id_for_log, int) else 0,
        operation_type="create_sheet",
        target_type="sheet",
        detail=detail,
    )

    return {
        "date": date_iso,
        "weekday": weekday,
        "created_count": len(sheet_results),
        "skipped_count": 0,
        "sheets": sheet_results,
    }


# ============================================================
# 工具5：删除工作表（外部可访问，不允许删除模板）
# ============================================================
def delete_sheet_and_sync(
    corp_id: str,
    secret: str,
    operator_userid: str,
    operator_name: str,
    sheet_name: str = None,
    sheet_id: str = None,
) -> Dict[str, Any]:
    """针对数据库第一个智能表格，删除指定工作表

    参数（二选一）：
        sheet_name: 工作表名称（推荐，对调用方更友好）
        sheet_id:   工作表 ID（优先使用，若同时提供则以 sheet_id 为准）

    校验规则：
        1. 必须提供 sheet_name 或 sheet_id 之一
        2. 数据库第一个智能表格必须存在
        3. 工作表必须在本地 sheets 表中存在（按 sheet_id/sheet_name 查询）
        4. 不允许删除模板工作表（templates 表中的 sheet_id 一律拒绝）
        5. 不允许删除文档内最后一张子表（企业微信限制）

    返回: {
        "sheet_id": str,
        "sheet_name": str,
        "deleted_at": str,        # ISO 时间
        "doc_id": str,
    }
    """
    # ---------- 步骤 0：参数与前置校验 ----------
    if not sheet_name and not sheet_id:
        raise ValueError("请提供 sheet_name 或 sheet_id 之一")

    doc_id = db.get_first_doc()
    if not doc_id:
        raise Exception("数据库中还没有智能表格，无法删除")

    # 优先按 sheet_id 查；若没给 sheet_id 则按 sheet_name 查
    if sheet_id:
        sheet_row = db.get_sheet_by_id(sheet_id)
        if not sheet_row:
            raise ValueError(f"工作表不存在（sheet_id={sheet_id}）")
        if not sheet_name:
            sheet_name = sheet_row["sheet_name"]
    else:
        sheet_row = db.get_sheet_by_name(sheet_name)
        if not sheet_row:
            raise ValueError(f"工作表不存在（sheet_name={sheet_name}）")
        sheet_id = sheet_row["sheet_id"]

    # 一致性校验：DB 里的 doc_id 必须是第一个智能表格的 doc_id
    if sheet_row["doc_id"] != doc_id:
        raise ValueError(
            f"该工作表不属于第一个智能表格（sheet 的 doc_id={sheet_row['doc_id']}，"
            f"第一个智能表格 doc_id={doc_id}），不允许跨文档删除"
        )

    # 校验 1：不允许删除模板工作表
    if db.is_template_sheet(sheet_id):
        raise ValueError(f"不允许删除模板工作表：{sheet_name}（sheet_id={sheet_id}）")

    # 操作人入库
    user_id = db.insert_user(operator_userid, operator_name)

    # ---------- 步骤 1：远端校验 + 删除 ----------
    with httpx.Client(timeout=30) as client:
        token = api_wework.get_access_token(client, corp_id, secret)

        # 校验 2：不允许删除文档内最后一张子表
        sheet_list_resp = api_wework.get_sheet_list(client, token, doc_id)
        remote_sheets = sheet_list_resp.get("sheet_list", [])
        if len(remote_sheets) <= 1:
            raise ValueError("文档内仅剩最后一张子表，企业微信不允许删除全部子表")

        # 执行远端删除
        api_wework.delete_sheet(client, token, doc_id, sheet_id)

    # ---------- 步骤 2：同步本地数据库 ----------
    deleted_rows = db.delete_sheet_by_id(sheet_id)
    if deleted_rows == 0:
        # 远端删除成功但本地无记录（理论上前面查重已经拦截），记录警告但不报错
        logging.warning(f"远端已删除，但本地 sheets 表无此记录：sheet_id={sheet_id}")

    # ---------- 步骤 3：操作日志 ----------
    deleted_at = datetime.now().isoformat(timespec="seconds")
    detail = {
        "sheet_id": sheet_id,
        "sheet_name": sheet_name,
        "doc_id": doc_id,
        "deleted_at": deleted_at,
        "operator": {"userid": operator_userid, "name": operator_name},
    }
    # target_id 用本地 sheets 表的原 id（如果有的话）
    target_id = sheet_row["id"] if "id" in sheet_row.keys() else 0
    db.insert_log(
        operator_id=user_id,
        target_id=target_id,
        operation_type="delete_sheet",
        target_type="sheet",
        detail=detail,
    )

    logging.info(f"删除工作表成功：{sheet_name}（sheet_id={sheet_id}）")
    return {
        "sheet_id": sheet_id,
        "sheet_name": sheet_name,
        "doc_id": doc_id,
        "deleted_at": deleted_at,
    }


# ============================================================
# 工具6：更新记录内容（订座信息）
# ============================================================

# 订座相关字段：这些字段中任一非空 → "是否已订"自动设为"已订座"
BOOKING_RELATED_FIELDS = ["客人称呼", "客人电话", "人数", "留菜", "留位人"]


def _extract_text_value(field_values: list) -> str:
    """从记录的某个字段值列表中提取纯文本值

    支持两种格式：
    - 文本字段: [{"type": "text", "text": "值"}]
    - 单选字段: [{"text": "选项"}]
    """
    if not field_values:
        return ""
    for item in field_values:
        if isinstance(item, dict):
            text = item.get("text", "")
            if text:
                return text
    return ""


def _build_update_value(field_type: str, value) -> list:
    """构造单个字段值的 API 封装格式

    - 单选字段: [{"text": str(value)}]
    - 其他字段（文本等）: [{"type": "text", "text": str(value)}]
    """
    if field_type == "FIELD_TYPE_SINGLE_SELECT":
        return [{"text": str(value)}]
    else:
        return [{"type": "text", "text": str(value)}]


def update_record_and_sync(
    corp_id: str,
    secret: str,
    operator_userid: str,
    operator_name: str,
    sheet_date: str,
    session: str,
    seat_name: str,
    fields: Dict[str, Any],
    default_sessions: List[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    """更新指定工作表中指定座位记录的字段值

    参数:
        corp_id, secret: 企业微信凭证
        operator_userid, operator_name: 操作人
        sheet_date: 目标日期（YYYY-MM-DD / MM-DD）
        session: 场次（lunch/dinner/午市/晚市）
        seat_name: 座位名称（如"北京房"）
        fields: 要更新的字段字典，如 {"客人称呼": "张三", "客人电话": "13800138000"}
        default_sessions: 场次默认配置

    订座规则:
        - BOOKING_RELATED_FIELDS 中任一字段非空 → "是否已订" = "已订座"
        - 全部为空 → "是否已订" = "未订座"
        （判断基于更新后的最终值，即当前值 + 更新值合并后）

    返回: {
        "sheet_name": str,
        "sheet_id": str,
        "seat_name": str,
        "record_id": str,
        "updated_fields": dict,   # 实际更新的字段和值
        "booking_status": str,    # "已订座" / "未订座"
    }
    """
    if default_sessions is None:
        default_sessions = [("lunch", "午市"), ("dinner", "晚市")]

    if not fields:
        raise ValueError("请至少提供一个要更新的字段")
    if not seat_name:
        raise ValueError("请提供座位名称 seat_name")

    # ---------- 步骤 0：解析参数，定位工作表 ----------
    target_date = _parse_date_str(sheet_date)
    normalized = _normalize_sessions(session, default_sessions)
    session_type, session_label = normalized[0]
    sheet_name = _make_sheet_name(target_date, session_label)

    # 从数据库查 sheet_id
    sheet_row = db.get_sheet_by_name(sheet_name)
    if not sheet_row:
        raise ValueError(
            f"工作表不存在：{sheet_name}（日期={target_date.isoformat()}, 场次={session_label}）"
        )
    sheet_id = sheet_row["sheet_id"]
    doc_id = sheet_row["doc_id"]

    # ---------- 步骤 1：获取 token + 字段列表 + 记录 ----------
    with httpx.Client(timeout=30) as client:
        token = api_wework.get_access_token(client, corp_id, secret)

        # 获取字段列表，建立 field_title → {field_id, field_type} 映射
        fields_resp = api_wework.get_fields(client, token, doc_id, sheet_id)
        field_map = {}
        for f in fields_resp.get("fields", []):
            field_map[f["field_title"]] = {
                "field_id": f["field_id"],
                "field_type": f.get("field_type", "FIELD_TYPE_TEXT"),
            }
        if not field_map:
            raise Exception(f"工作表 {sheet_name} 没有任何字段")

        # 查询记录，定位目标座位
        records_resp = api_wework.get_records(client, token, doc_id, sheet_id, limit=100)
        all_records = records_resp.get("records", [])
        total = records_resp.get("total", len(all_records))

        # 防御性分页（座位一般47条，一次够）
        next_offset = records_resp.get("next_offset")
        while next_offset and next_offset < total:
            more_resp = api_wework.get_records(client, token, doc_id, sheet_id, offset=next_offset, limit=100)
            all_records.extend(more_resp.get("records", []))
            next_offset = more_resp.get("next_offset")

        # 找到座位名称匹配的记录
        target_record = None
        for rec in all_records:
            values = rec.get("values", {})
            seat_val = _extract_text_value(values.get("座位名称", []))
            if seat_val == seat_name:
                target_record = rec
                break

        if not target_record:
            raise ValueError(f"在工作表 {sheet_name} 中未找到座位：{seat_name}")

        record_id = target_record["record_id"]
        current_values = target_record.get("values", {})

        # ---------- 步骤 2：应用订座规则 ----------
        # 合并当前值和更新值（用于判断订座状态）
        merged_booking_values = {}
        for field_title in BOOKING_RELATED_FIELDS:
            current_val = _extract_text_value(current_values.get(field_title, []))
            if field_title in fields:
                merged_booking_values[field_title] = str(fields[field_title]) if fields[field_title] else ""
            else:
                merged_booking_values[field_title] = current_val

        any_non_empty = any(v for v in merged_booking_values.values())
        booking_status = "已订座" if any_non_empty else "未订座"

        # 构造最终的更新字段（包含自动计算的"是否已订"）
        final_fields = dict(fields)
        final_fields["是否已订"] = booking_status  # 自动覆盖

        # ---------- 步骤 3：构造 payload 并更新 ----------
        # 校验字段名是否存在
        unknown_fields = [f for f in final_fields if f not in field_map]
        if unknown_fields:
            raise ValueError(f"以下字段不存在于工作表中：{unknown_fields}")

        update_values = {}
        for field_title, value in final_fields.items():
            field_type = field_map[field_title]["field_type"]
            update_values[field_title] = _build_update_value(field_type, value)

        api_wework.update_records(
            client, token, doc_id, sheet_id,
            [{"record_id": record_id, "values": update_values}]
        )

    # ---------- 步骤 4：操作日志 ----------
    user_id = db.insert_user(operator_userid, operator_name)
    detail = {
        "sheet_name": sheet_name,
        "sheet_id": sheet_id,
        "seat_name": seat_name,
        "record_id": record_id,
        "updated_fields": final_fields,
        "booking_status": booking_status,
        "operator": {"userid": operator_userid, "name": operator_name},
    }
    db.insert_log(
        operator_id=user_id,
        target_id=sheet_row["id"],
        operation_type="update_record",
        target_type="sheet",
        detail=detail,
    )

    logging.info(f"更新记录成功：{sheet_name} / {seat_name} → {final_fields}")
    return {
        "sheet_name": sheet_name,
        "sheet_id": sheet_id,
        "seat_name": seat_name,
        "record_id": record_id,
        "updated_fields": final_fields,
        "booking_status": booking_status,
    }


# ============================================================
# 工具7：添加记录（向指定工作表添加一条新记录）
# ============================================================
def add_record_and_sync(
    corp_id: str,
    secret: str,
    operator_userid: str,
    operator_name: str,
    sheet_date: str,
    session: str,
    seat_name: str,
    fields: Dict[str, Any] = None,
    default_sessions: List[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    """向指定工作表添加一条新记录

    默认值：
        - 座位名称 = 传入的 seat_name
        - 座位类型 = "大厅"
        - 是否已订 = "未订座"
        - 其余字段 = 空

    订座规则（与 update_record 一致）：
        - BOOKING_RELATED_FIELDS 中任一非空 → "是否已订" = "已订座"
        - 全部为空 → "是否已订" = "未订座"

    参数:
        seat_name: 新座位的名称（必填）
        fields:    额外要填写的字段（可选，覆盖默认值）

    返回: {
        "sheet_name": str,
        "sheet_id": str,
        "seat_name": str,
        "record_id": str,
        "fields": dict,         # 最终写入的字段
        "booking_status": str,
    }
    """
    if default_sessions is None:
        default_sessions = [("lunch", "午市"), ("dinner", "晚市")]

    if not seat_name:
        raise ValueError("请提供座位名称 seat_name")

    if fields is None:
        fields = {}

    # ---------- 步骤 0：解析参数，定位工作表 ----------
    target_date = _parse_date_str(sheet_date)
    normalized = _normalize_sessions(session, default_sessions)
    _session_type, session_label = normalized[0]
    sheet_name = _make_sheet_name(target_date, session_label)

    sheet_row = db.get_sheet_by_name(sheet_name)
    if not sheet_row:
        raise ValueError(
            f"工作表不存在：{sheet_name}（日期={target_date.isoformat()}, 场次={session_label}）"
        )
    sheet_id = sheet_row["sheet_id"]
    doc_id = sheet_row["doc_id"]

    # ---------- 步骤 1：获取字段列表 ----------
    with httpx.Client(timeout=30) as client:
        token = api_wework.get_access_token(client, corp_id, secret)

        fields_resp = api_wework.get_fields(client, token, doc_id, sheet_id)
        field_map = {}
        for f in fields_resp.get("fields", []):
            field_map[f["field_title"]] = {
                "field_id": f["field_id"],
                "field_type": f.get("field_type", "FIELD_TYPE_TEXT"),
            }
        if not field_map:
            raise Exception(f"工作表 {sheet_name} 没有任何字段")

        # ---------- 步骤 2：构造记录值 ----------
        # 默认值
        final_fields = {"座位名称": seat_name}
        # 用户传入的 fields 覆盖默认值（座位名称也可以被覆盖）
        final_fields.update(fields)
        # 确保有默认的座位类型和是否已订
        if "座位类型" not in final_fields:
            final_fields["座位类型"] = "大厅"

        # ---------- 步骤 3：应用订座规则 ----------
        merged_booking_values = {}
        for field_title in BOOKING_RELATED_FIELDS:
            val = final_fields.get(field_title, "")
            merged_booking_values[field_title] = str(val) if val else ""

        any_non_empty = any(v for v in merged_booking_values.values())
        booking_status = "已订座" if any_non_empty else "未订座"
        final_fields["是否已订"] = booking_status

        # ---------- 步骤 4：校验字段名 + 构造 payload ----------
        unknown_fields = [f for f in final_fields if f not in field_map]
        if unknown_fields:
            raise ValueError(f"以下字段不存在于工作表中：{unknown_fields}")

        # 构造记录：只填 final_fields 中的字段，其余字段由企业微信默认为空
        record_values = {}
        for field_title, value in final_fields.items():
            field_type = field_map[field_title]["field_type"]
            record_values[field_title] = _build_update_value(field_type, value)

        # 添加记录
        add_resp = api_wework.add_records(
            client, token, doc_id, sheet_id,
            [{"values": record_values}]
        )
        # 从返回值中提取 record_id
        added_records = add_resp.get("records", [])
        record_id = added_records[0].get("record_id") if added_records else None

    # ---------- 步骤 5：操作日志 ----------
    user_id = db.insert_user(operator_userid, operator_name)
    detail = {
        "sheet_name": sheet_name,
        "sheet_id": sheet_id,
        "seat_name": seat_name,
        "record_id": record_id,
        "fields": final_fields,
        "booking_status": booking_status,
        "operator": {"userid": operator_userid, "name": operator_name},
    }
    db.insert_log(
        operator_id=user_id,
        target_id=sheet_row["id"],
        operation_type="add_record",
        target_type="sheet",
        detail=detail,
    )

    logging.info(f"添加记录成功：{sheet_name} / {seat_name}（record_id={record_id}）")
    return {
        "sheet_name": sheet_name,
        "sheet_id": sheet_id,
        "seat_name": seat_name,
        "record_id": record_id,
        "fields": final_fields,
        "booking_status": booking_status,
    }


# ============================================================
# 工具8：删除记录（从指定工作表删除指定记录）
# ============================================================
def delete_record_and_sync(
    corp_id: str,
    secret: str,
    operator_userid: str,
    operator_name: str,
    sheet_date: str,
    session: str,
    seat_name: str = None,
    record_id: str = None,
    default_sessions: List[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    """从指定工作表删除指定记录

    定位方式（二选一，record_id 优先）：
        - record_id: 直接按记录 ID 删除
        - seat_name:  按座位名称查找后删除

    参数:
        sheet_date + session: 确定工作表
        record_id:   记录 ID（优先）
        seat_name:   座位名称（若未提供 record_id 则按此查找）

    返回: {
        "sheet_name": str,
        "sheet_id": str,
        "deleted_record_id": str,
        "seat_name": str,
        "deleted_at": str,
    }
    """
    if default_sessions is None:
        default_sessions = [("lunch", "午市"), ("dinner", "晚市")]

    if not record_id and not seat_name:
        raise ValueError("请提供 record_id 或 seat_name 之一来定位记录")

    # ---------- 步骤 0：解析参数，定位工作表 ----------
    target_date = _parse_date_str(sheet_date)
    normalized = _normalize_sessions(session, default_sessions)
    _session_type, session_label = normalized[0]
    sheet_name = _make_sheet_name(target_date, session_label)

    sheet_row = db.get_sheet_by_name(sheet_name)
    if not sheet_row:
        raise ValueError(
            f"工作表不存在：{sheet_name}（日期={target_date.isoformat()}, 场次={session_label}）"
        )
    sheet_id = sheet_row["sheet_id"]
    doc_id = sheet_row["doc_id"]

    # ---------- 步骤 1：定位记录 ----------
    with httpx.Client(timeout=30) as client:
        token = api_wework.get_access_token(client, corp_id, secret)

        if record_id:
            # 按 record_id 删除（不需要先查询记录）
            target_record_id = record_id
            target_seat_name = seat_name or ""
        else:
            # 按 seat_name 查找记录
            records_resp = api_wework.get_records(client, token, doc_id, sheet_id, limit=100)
            all_records = records_resp.get("records", [])
            total = records_resp.get("total", len(all_records))

            # 防御性分页
            next_offset = records_resp.get("next_offset")
            while next_offset and next_offset < total:
                more_resp = api_wework.get_records(client, token, doc_id, sheet_id, offset=next_offset, limit=100)
                all_records.extend(more_resp.get("records", []))
                next_offset = more_resp.get("next_offset")

            target_record = None
            for rec in all_records:
                values = rec.get("values", {})
                seat_val = _extract_text_value(values.get("座位名称", []))
                if seat_val == seat_name:
                    target_record = rec
                    break

            if not target_record:
                raise ValueError(f"在工作表 {sheet_name} 中未找到座位：{seat_name}")

            target_record_id = target_record["record_id"]
            target_seat_name = seat_name

        # ---------- 步骤 2：删除记录 ----------
        api_wework.delete_records(client, token, doc_id, sheet_id, [target_record_id])

    # ---------- 步骤 3：操作日志 ----------
    user_id = db.insert_user(operator_userid, operator_name)
    deleted_at = datetime.now().isoformat(timespec="seconds")
    detail = {
        "sheet_name": sheet_name,
        "sheet_id": sheet_id,
        "deleted_record_id": target_record_id,
        "seat_name": target_seat_name,
        "deleted_at": deleted_at,
        "operator": {"userid": operator_userid, "name": operator_name},
    }
    db.insert_log(
        operator_id=user_id,
        target_id=sheet_row["id"],
        operation_type="delete_record",
        target_type="sheet",
        detail=detail,
    )

    logging.info(f"删除记录成功：{sheet_name} / {target_seat_name}（record_id={target_record_id}）")
    return {
        "sheet_name": sheet_name,
        "sheet_id": sheet_id,
        "deleted_record_id": target_record_id,
        "seat_name": target_seat_name,
        "deleted_at": deleted_at,
    }