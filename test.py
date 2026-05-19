import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/")
async def home():
    return HTMLResponse("<h1 style='color:white;background:black'>Meridian Works</h1>")

uvicorn.run(app, host="127.0.0.1", port=8002)