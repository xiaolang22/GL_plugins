from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.post("/test")
async def hello_plugin():
    # 插件被调用时返回 Hello World
    return {"content": "Hello, World!"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)