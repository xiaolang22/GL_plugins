import os
import logging
import json
from fastapi import FastAPI, Request, Response
import uvicorn
import httpx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

# ========== 配置区域（请替换为你的真实信息） ==========
CORP_ID = "ww742ff47a509b856e"           # 企业微信后台「我的企业」-「企业信息」中获取
SECRET = "Iu6AYICGeiAe2kx3YyTSefTEZsld42U6EkGsQ2ON2QA"     # 自建应用详情页中的 Secret
# ===================================================

# 用于存储创建的表格信息（生产环境建议使用数据库）
created_docs = {}


def get_access_token() -> str:
    """获取 access_token"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={CORP_ID}&corpsecret={SECRET}"
    resp = httpx.get(url)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"获取access_token失败: {result}")
    return result["access_token"]


def create_smart_sheet(access_token: str, doc_name: str, admin_users: list = None) -> dict:
    """
    创建智能表格
    文档：https://developer.work.weixin.qq.com/document/path/97460
    """
    url = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/create_doc?access_token={access_token}"
    payload = {
        "doc_type": 10,  # 10 = 智能表格
        "doc_name": doc_name,
    }
    if admin_users:
        payload["admin_users"] = admin_users

    resp = httpx.post(url, json=payload)
    result = resp.json()
    if result.get("errcode") != 0:
        raise Exception(f"创建智能表格失败: {result}")
    return result


def add_blank_sheet(access_token: str, docid: str, sheet_title: str, index: int = None) -> dict:
    """
    在智能表格中添加一个空白工作表
    文档：https://developer.work.weixin.qq.com/document/path/99896
    """
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
        raise Exception(f"添加工作表失败: {result}")
    return result


@app.post("/create_sheet_with_blank")
async def create_sheet_with_blank(request: Request):
    """
    智能机器人调用的插件接口：
    1. 创建一个指定名称的智能表格
    2. 在表格中新建一个空白工作表
    """
    try:
        # 1. 解析请求体（智能机器人传来的参数）
        body = await request.body()
        if body:
            data = json.loads(body)
        else:
            data = {}

        doc_name = data.get("doc_name", "默认智能表格")
        sheet_title = data.get("sheet_title", "空白工作表")
        admin_users = data.get("admin_users", [])

        logging.info(f"收到请求: doc_name={doc_name}, sheet_title={sheet_title}")

        # 2. 获取 access_token
        token = get_access_token()
        logging.info("获取 access_token 成功")

        # 3. 创建智能表格
        create_result = create_smart_sheet(token, doc_name, admin_users)
        docid = create_result.get("docid")
        doc_url = create_result.get("url")
        logging.info(f"创建智能表格成功: docid={docid}, url={doc_url}")

        # 4. 在表格中添加空白工作表
        sheet_result = add_blank_sheet(token, docid, sheet_title)
        sheet_id = sheet_result.get("properties", {}).get("sheet_id")
        logging.info(f"添加空白工作表成功: sheet_id={sheet_id}")

        # 5. 存储 docid 和 sheet_id（生产环境建议存入数据库）
        created_docs[docid] = {
            "doc_name": doc_name,
            "doc_url": doc_url,
            "sheet_title": sheet_title,
            "sheet_id": sheet_id,
        }

        # 6. 返回结果给智能机器人
        reply_content = (
            f"✅ 已成功创建智能表格「{doc_name}」\n"
            f"📎 访问链接：{doc_url}\n"
            f"📄 已创建空白工作表：「{sheet_title}」(ID: {sheet_id})"
        )
        return {"content": reply_content}

    except Exception as e:
        logging.error(f"处理请求异常: {e}")
        return {"content": f"❌ 操作失败: {str(e)}"}


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)