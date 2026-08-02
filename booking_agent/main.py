import sys
import os
import logging
import json
from fastapi import FastAPI, Request
import uvicorn

# 添加当前目录到path以便导入模块
sys.path.append(os.path.dirname(__file__))

from db import init_db
from composite import create_smart_sheet_and_sync, create_template_sheet_and_sync

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= 可调参数 =================
CORP_ID = "ww742ff47a509b856e"
SECRET = "Iu6AYICGeiAe2kx3YyTSefTEZsld42U6EkGsQ2ON2QA"
DEFAULT_ADMIN_USERS = ["ChenDaHong"]  # 可指定初始管理员 userid 列表
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

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)