from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, leads, campaigns, outreach, meetings, crm, analytics, team, settings, billing, jobs

app = FastAPI(title="AI Sales Teammate API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(leads.router, prefix="/leads", tags=["leads"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(outreach.router, prefix="/outreach", tags=["outreach"])
app.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
app.include_router(crm.router, prefix="/crm", tags=["crm"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(team.router, prefix="/team", tags=["team"])
app.include_router(settings.router, prefix="/settings", tags=["settings"])
app.include_router(billing.router, prefix="/billing", tags=["billing"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])


@app.get("/health")
async def health():
    return {"status": "ok"}
