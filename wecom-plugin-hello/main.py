import sys
import os

# 添加加解密库的路径（根据你的项目结构调整）
# weworkapi_python-master 在上级目录，且 Python3 版本在 callback_python3 子目录下
LIB_PATH = os.path.join(os.path.dirname(__file__), '..', 'weworkapi_python-master', 'callback_python3')
sys.path.insert(0, LIB_PATH)

from fastapi import FastAPI, Request, Query
import uvicorn

# 从企业微信加解密库导入
from WXBizMsgCrypt import WXBizMsgCrypt

app = FastAPI()

# ========== 配置信息（从企业微信后台获取）==========
TOKEN = "4tGHzTEzQVLNykfP6f8"
ENCODING_AES_KEY = "phrLP0vxU8RxeJ5cDTz338qkz8cNIVXtzSlWm9Oijkd"
# ⚠️ 重要：CORP_ID 请替换为你的企业微信 CorpID
# 路径：企业微信管理后台 → 我的企业 → 企业信息 → CorpID
CORP_ID = "ww742ff47a509b856e"  # 例如：ww1234567890abcdef

# 初始化加解密工具
# 注意：智能机器人场景下，最后一个参数（receiveid）传空字符串
wxcpt = WXBizMsgCrypt(TOKEN, ENCODING_AES_KEY, CORP_ID)


@app.get("/test")
async def verify_url(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...)
):
    """
    企业微信验证回调 URL 时使用 GET 请求
    必须解密 echostr 并返回明文
    """
    try:
        # 调用官方库的 VerifyURL 方法
        # 返回: (ret_code, decrypted_echostr)
        ret, sReplyEchoStr = wxcpt.VerifyURL(msg_signature, timestamp, nonce, echostr)
        
        if ret != 0:
            # 验证失败，返回空字符串
            return ""
        
        # 返回解密后的明文（注意：不能加引号、不能有BOM头、不能有换行符）
        return sReplyEchoStr
    except Exception as e:
        # 异常时返回空字符串
        return ""


@app.post("/test")
async def hello_plugin():
    """
    插件被调用时使用 POST 请求
    这里返回 Hello World
    """
    return {"content": "Hello, World!"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)