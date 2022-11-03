#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.

from fastapi import FastAPI

from connector_builder.impl.default_api import DefaultApiImpl
from connector_builder.generated.apis.default_api_interface import initialize_router

app = FastAPI(
    title="Connector Builder Server API",
    description="Connector Builder Server API ",
    version="1.0.0",
)

app.include_router(initialize_router(DefaultApiImpl()))
