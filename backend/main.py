from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from app.db import init_db_on_startup
from app.routers.diff import router as diff_router
from app.routers.promotions import router as promotions_router

# Load .env from backend/ directory
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

app = FastAPI(title="GrowthBook Feature Flag Ops - Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(diff_router)
app.include_router(promotions_router)

@app.on_event("startup")
async def startup_event():
    await init_db_on_startup()

@app.get("/api/health")
async def health():
    return {"status": "ok"}
