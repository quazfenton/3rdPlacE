from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from config.database import engine, Base
from api.insurance_api import app as insurance_api
from services.lock_integration import AccessGrantService, KisiAdapter, SchlageAdapter, GenericQRAdapter
import uvicorn
import os


# Create database tables
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown


# Main FastAPI application
app = FastAPI(
    title="Third Place Platform",
    version="1.0.0",
    description="Infrastructure for recurring physical community spaces",
    lifespan=lifespan
)

# Include the insurance API routes
app.include_router(insurance_api, prefix="/api/v1", tags=["insurance"])

# Add a main health check endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to the Third Place Platform API", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "Main API Gateway"}


# Initialize lock integration service
access_grant_service = AccessGrantService()
access_grant_service.register_adapter("kisi", KisiAdapter(api_key=os.getenv("KISI_API_KEY", "test"), api_secret=os.getenv("KISI_API_SECRET", "test")))
access_grant_service.register_adapter("schlage", SchlageAdapter(api_key=os.getenv("SCHLAGE_API_KEY", "test")))
access_grant_service.register_adapter("generic", GenericQRAdapter(secret_key=os.getenv("JWT_SECRET_KEY", "supersecretkey")))


# Add the access grant service to the app state so it can be accessed by other components
@app.on_event("startup")
def startup_event():
    app.state.access_grant_service = access_grant_service


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)