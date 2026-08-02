import httpx
import logging
from typing import List, Dict, Any

# 这些参数将在 main.py 中传递，此处不硬编码
def get_access_token(corp_id: str, secret: str) -> str:
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}"
    resp = httpx.get(url)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"获取access_token失败: {result}")
    return result["access_token"]

def create_doc(access_token: str, doc_name: str, admin_users: List[str] = None) -> Dict[str, Any]:
    """创建智能表格，doc_type=10"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/create_doc?access_token={access_token}"
    payload = {
        "doc_type": 10,
        "doc_name": doc_name,
    }
    if admin_users:
        payload["admin_users"] = admin_users
    resp = httpx.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"创建智能表格失败: {result}")
    return result  # 包含 docid, url

def add_sheet(access_token: str, docid: str, sheet_title: str, index: int = None) -> Dict[str, Any]:
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
    resp = httpx.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"添加子表失败: {result}")
    return result  # 包含 properties.sheet_id

def add_fields(access_token: str, docid: str, sheet_id: str, fields: List[Dict]) -> Dict[str, Any]:
    """添加字段"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/add_fields?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "fields": fields
    }
    resp = httpx.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"添加字段失败: {result}")
    return result

def add_records(access_token: str, docid: str, sheet_id: str, records: List[Dict]) -> Dict[str, Any]:
    """添加记录"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/add_records?access_token={access_token}"
    payload = {
        "docid": docid,
        "sheet_id": sheet_id,
        "records": records
    }
    resp = httpx.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"添加记录失败: {result}")
    return result