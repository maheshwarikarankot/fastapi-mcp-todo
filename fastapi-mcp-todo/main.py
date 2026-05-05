"""
Simple FastAPI ToDo CRUD Application (SQLite).

API endpoints:
- GET  /              -> welcome message
- GET  /todos        -> list all todos
- GET  /todos/{id}  -> get a single todo
- POST /todos        -> create a new todo
- PUT  /todos/{id}  -> update an existing todo
- DELETE /todos/{id} -> delete a todo
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi_mcp import FastApiMCP
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "todos.db"

app = FastAPI(
    title="Mahi ToDo API",
    description="A simple, local SQLite-backed ToDo CRUD API.",
    version="1.0.0",
)

# -----------------------------
# MCP server (exposes FastAPI ops as MCP tools)
# -----------------------------

# Converts tagged FastAPI operations into MCP tools, mounted under `/mcp`.
mcp = FastApiMCP(app, include_operations=["get_all_todos", "get_todo", "add_todo", "update_todo", "delete_todo"])
mcp.mount(mount_path="/mcp")


# -----------------------------
# Pydantic models (request/response)
# -----------------------------


class TodoCreate(BaseModel):
    content: str = Field(min_length=1, max_length=1024, description="Todo content")


class TodoUpdate(BaseModel):
    content: str | None = Field(
        default=None, min_length=1, max_length=1024, description="Updated content"
    )
    completed: bool | None = Field(default=None, description="Updated completion status")


class Todo(BaseModel):
    todo_id: int
    content: str
    completed: bool = Field(default=False)


# -----------------------------
# SQLite helpers
# -----------------------------


def _connect() -> sqlite3.Connection:
    """Create a new database connection for the current request."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    """Create required tables if they don't exist."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                todo_id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


@app.on_event("startup")
def on_startup() -> None:
    _init_db()


def _row_to_todo(row: sqlite3.Row) -> Todo:
    # sqlite stores booleans as INTEGER; normalize to Python bool.
    return Todo(
        todo_id=int(row["todo_id"]),
        content=str(row["content"]),
        completed=bool(row["completed"]),
    )


def _get_todo_or_404(todo_id: int) -> Todo:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT todo_id, content, completed FROM todos WHERE todo_id = ?",
            (todo_id,),
        )
        row = cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Todo with todo_id={todo_id} not found.",
        )

    return _row_to_todo(row)


# -----------------------------
# Routes
# -----------------------------


@app.get("/", tags=["Root"])
def root() -> dict[str, str]:
    """Return a basic welcome message."""
    return {"message": "Welcome to the Mahi ToDo API"}


@app.get("/todos", response_model=list[Todo], tags=["Todos"], operation_id="get_all_todos")
def get_all_todos() -> list[Todo]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT todo_id, content, completed FROM todos ORDER BY todo_id ASC"
        )
        rows = cur.fetchall()

    return [_row_to_todo(row) for row in rows]


@app.get("/todos/{todo_id}", response_model=Todo, tags=["Todos"], operation_id="get_todo")
def get_todo(todo_id: int) -> Todo:
    return _get_todo_or_404(todo_id)


@app.post(
    "/todos",
    response_model=Todo,
    status_code=status.HTTP_201_CREATED,
    tags=["Todos"],
    operation_id="add_todo",
)
def add_todo(todo: TodoCreate) -> Todo:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO todos (content, completed) VALUES (?, ?)",
            (todo.content, 0),
        )
        conn.commit()
        new_id = int(cur.lastrowid)

    return _get_todo_or_404(new_id)


@app.put("/todos/{todo_id}", response_model=Todo, tags=["Todos"], operation_id="update_todo")
def update_todo(todo_id: int, todo: TodoUpdate) -> Todo:
    update_fields: list[str] = []
    params: list[Any] = []

    if todo.content is not None:
        update_fields.append("content = ?")
        params.append(todo.content)

    if todo.completed is not None:
        update_fields.append("completed = ?")
        params.append(1 if todo.completed else 0)

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update fields provided. Send at least one of: content, completed.",
        )

    with _connect() as conn:
        sql = f"UPDATE todos SET {', '.join(update_fields)} WHERE todo_id = ?"
        params.append(todo_id)
        cur = conn.execute(sql, tuple(params))
        conn.commit()

        if cur.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Todo with todo_id={todo_id} not found.",
            )

    return _get_todo_or_404(todo_id)


@app.delete("/todos/{todo_id}", tags=["Todos"], operation_id="delete_todo")
def delete_todo(todo_id: int) -> dict[str, Any]:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM todos WHERE todo_id = ?", (todo_id,))
        conn.commit()

        if cur.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Todo with todo_id={todo_id} not found.",
            )

    return {"message": "Todo deleted successfully.", "todo_id": todo_id}