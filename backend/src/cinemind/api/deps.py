"""FastAPI dependencies: settings and a DB session per request."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from cinemind.core.config import Settings


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


def get_session(request: Request) -> Iterator[Session]:
    with get_factory(request)() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
FactoryDep = Annotated[sessionmaker[Session], Depends(get_factory)]
