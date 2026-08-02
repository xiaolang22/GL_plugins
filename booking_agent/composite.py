import logging
from typing import List, Dict, Any
import api_wework
import db

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

    # 2. 定义字段（按顺序）
    fields = [
        {"field_title": "座位名称", "field_type": "text"},
        {"field_title": "座位容量", "field_type": "number"},
        {"field_title": "座位备注", "field_type": "text"},
        {"field_title": "客人称呼", "field_type": "text"},
        {"field_title": "客人电话", "field_type": "text"},
        {"field_title": "人数", "field_type": "text"},  # 实际应为数字，但需求中留空，使用文本
        {"field_title": "留菜", "field_type": "text"},
        {"field_title": "留位人", "field_type": "text"},
        {"field_title": "座位类型", "field_type": "select", "options": {"options": ["房间", "大厅"]}},
        {"field_title": "是否已订", "field_type": "select", "options": {"options": ["已订座", "未订座"]}},
    ]
    api_wework.add_fields(token, doc_id, sheet_id, fields)

    # 3. 添加记录
    records = []
    for name, capacity, remark, seat_type in SEAT_DATA:
        records.append({
            "values": {
                "座位名称": name,
                "座位容量": capacity,
                "座位备注": remark,
                "座位类型": seat_type,
                "是否已订": "未订座"
            }
        })
    api_wework.add_records(token, doc_id, sheet_id, records)

    # 4. 同步数据库：插入模板记录
    template_db_id = db.insert_template(doc_id, sheet_id, template_name, operator_userid)

    # 5. 日志
    user_id = db.insert_user(operator_userid, operator_name)
    db.insert_log(
        operator_id=user_id,
        target_id=template_db_id,
        operation_type="create_template",
        target_type="template",
        detail={"template_name": template_name, "sheet_id": sheet_id}
    )

    return {"sheet_id": sheet_id, "template_db_id": template_db_id}