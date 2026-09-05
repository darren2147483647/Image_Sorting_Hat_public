"""
圖像分類帽 — FastAPI 主應用程式
動漫二創影像管理工具
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS
from database import init_db, get_db, get_db_stats
from routes import images, scan, character_tags, individual_tags, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    # Startup
    await init_db()
    print("🎩 圖像分類帽 — 後端伺服器已啟動")
    yield
    # Shutdown
    print("🎩 圖像分類帽 — 後端伺服器已關閉")


app = FastAPI(
    title="圖像分類帽",
    description="動漫二創影像管理工具 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(images.router)
app.include_router(scan.router)
app.include_router(character_tags.router)
app.include_router(individual_tags.router)
app.include_router(search.router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "app": "圖像分類帽", "version": "0.1.0"}


@app.get("/api/stats")
async def get_stats(db=Depends(get_db)):
    """Get database statistics overview."""
    stats = await get_db_stats(db)
    return {
        "total_images": stats.get("images", 0),
        "total_characters": stats.get("characters", 0),
        "total_franchises": stats.get("franchises", 0),
        "total_artists": stats.get("artists", 0),
        "total_character_tags": stats.get("images_with_character", 0),
        "total_artist_tags": stats.get("images_with_artist", 0),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
