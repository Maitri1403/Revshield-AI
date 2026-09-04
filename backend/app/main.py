from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers import auth, data, dashboard, risk, recovery, offers, assistant

app = FastAPI(
    title="RevShield AI",
    description="AI-powered revenue protection, recovery & intelligence platform.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://revshield-ai.netlify.app"],  # MVP / local use — restrict this before any real deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


app.include_router(auth.router)
app.include_router(data.router)
app.include_router(dashboard.router)
app.include_router(risk.router)
app.include_router(recovery.router)
app.include_router(offers.router)
app.include_router(assistant.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "RevShield AI backend"}
