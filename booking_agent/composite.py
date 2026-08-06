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

    # 5. 同步数据库：插入模板记录
    template_db_id = db.insert_template(doc_id, sheet_id, template_name, operator_userid)

    # 6. 日志
    user_id = db.insert_user(operator_userid, operator_name)
    db.insert_log(
        operator_id=user_id,
        target_id=template_db_id,
        operation_type="create_template",
        target_type="template",
        detail={"template_name": template_name, "sheet_id": sheet_id}
    )

    return {"sheet_id": sheet_id, "template_db_id": template_db_id}