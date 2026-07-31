import sys
import os
import logging
import json
from fastapi import FastAPI, Request, Response
import uvicorn

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

@app.post("/hello")
async def handle_plugin(request: Request):
    try:
        # 打印请求体用于调试
        body = await request.body()
        if body:
            logging.info(f"请求体内容: {body.decode('utf-8')}")
            data = json.loads(body)
            logging.info(f"解析后: {data}")
        else:
            logging.info("请求体为空")

        # 你的业务逻辑
        reply_content = "Hello, World!!!!"

        # 构造返回JSON
        response_data = {
            "content": reply_content
        }
        response_json = json.dumps(response_data, ensure_ascii=False)
        logging.info(f"返回JSON: {response_json}")

        return Response(
            content=response_json,
            media_type="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"异常: {e}")
        return Response(
            content=json.dumps({"error": "internal error"}),
            media_type="application/json",
            status_code=500
        )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)