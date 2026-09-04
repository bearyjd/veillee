"""Shared application state and request dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Request

from ..config import Settings
from ..db import connect
from ..questions import QuestionBank, load_bank


@dataclass
class AppState:
    """Mutable only where it must be: the bank is reloaded when he adds a question."""

    settings: Settings
    bank: QuestionBank

    def reload_bank(self) -> None:
        self.bank = load_bank(self.settings.questions_dir, self.settings.custom_questions_path)


def app_state(request: Request) -> AppState:
    state: AppState = request.app.state.veillee
    return state


def get_settings(request: Request) -> Settings:
    return app_state(request).settings


def get_bank(request: Request) -> QuestionBank:
    return app_state(request).bank


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """One short-lived connection per request. WAL makes this cheap."""
    connection = connect(app_state(request).settings.db_path)
    try:
        yield connection
    finally:
        connection.close()
