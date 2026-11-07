from importlib.metadata import version

from fastapi import FastAPI

from airsight.api.routes import health, model, readings, sensors


def create_app() -> FastAPI:
    app = FastAPI(title="AirSight API", version=version("airsight"))
    app.include_router(health.router, prefix="/v1")
    app.include_router(sensors.router, prefix="/v1")
    app.include_router(readings.router, prefix="/v1")
    app.include_router(model.router, prefix="/v1")
    return app


app = create_app()
