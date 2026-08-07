import httpx
import logging
from typing import List, Dict, Any

# 这些参数将在 main.py 中传递，此处不硬编码
def get_access_token(client: httpx.Client, corp_id: str, secret: str) -> str:
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}"
    resp = client.get(url)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"获取access_token失败: {result}")
    return result["access_token"]

def create_doc(client: httpx.Client, access_token: str, doc_name: str, admin_users: List[str] = None) -> Dict[str, Any]:
    """创建智能表格，doc_type=10"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/create_doc?access_token={access_token}"
    payload = {
        "doc_type": 10,
        "doc_name": doc_name,
    }
    if admin_users:
        payload["admin_users"] = admin_users
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"创建智能表格失败: {result}")
    return result  # 包含 docid, url

def add_sheet(client: httpx.Client, access_token: str, docid: str, sheet_title: str, index: int = None) -> Dict[str, Any]:
    """添加子表"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/add_sheet?access_token={access_token}"
    payload = {
        "docid": docid,
        "properties": {
            "title": sheet_title,
        }
    }
    if index is not None:
        payload["properties"]["index"] = index
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"添加子表失败: {result}")
    return result  # 包含 properties.sheet_id

def add_fields(client: httpx.Client, access_token: str, docid: str, sheet_id: str, fields: List[Dict]) -> Dict[str, Any]:
    """添加字段"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/add_fields?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "fields": fields
    }
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"添加字段失败: {result}")
    return result

def get_fields(client: httpx.Client, access_token: str, docid: str, sheet_id: str, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
    """查询字段"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/get_fields?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "offset": offset,
        "limit": limit
    }
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"查询字段失败: {result}")
    return result  # 包含 fields: [{field_id, field_title, field_type, ...}]

def delete_fields(client: httpx.Client, access_token: str, docid: str, sheet_id: str, field_ids: List[str]) -> Dict[str, Any]:
    """删除字段"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/delete_fields?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "field_ids": field_ids
    }
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"删除字段失败: {result}")
    return result

def update_fields(client: httpx.Client, access_token: str, docid: str, sheet_id: str, fields: List[Dict]) -> Dict[str, Any]:
    """更新字段（只能更新字段标题和属性，不能更新字段类型）"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/update_fields?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "fields": fields
    }
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"更新字段失败: {result}")
    return result

def get_views(client: httpx.Client, access_token: str, docid: str, sheet_id: str, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
    """查询视图"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/get_views?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "offset": offset,
        "limit": limit
    }
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"查询视图失败: {result}")
    return result  # 包含 views: [{view_id, view_title, view_type, property}]

def update_view(client: httpx.Client, access_token: str, docid: str, sheet_id: str, view_id: str, property: Dict) -> Dict[str, Any]:
    """更新视图（可设置排序/过滤/分组/填色等配置）"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/update_view?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "view_id": view_id,
        "property": property
    }
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"更新视图失败: {result}")
    return result

def add_records(client: httpx.Client, access_token: str, docid: str, sheet_id: str, records: List[Dict]) -> Dict[str, Any]:
    """添加记录"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/add_records?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "records": records
    }
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"添加记录失败: {result}")
    return result

def get_records(client: httpx.Client, access_token: str, docid: str, sheet_id: str, offset: int = 0, limit: int = 100, view_id: str = None, key_word: str = None) -> Dict[str, Any]:
    """查询记录（用于幂等性检查：判断记录是否已存在）"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/get_records?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "offset": offset,
        "limit": limit
    }
    if view_id:
        payload["view_id"] = view_id
    if key_word:
        payload["key_word"] = key_word
    resp = client.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"查询记录失败: {result}")
    return result  # 包含 total, records, next_offset
