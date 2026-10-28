"""
StorageAdapter - the storage-neutral contract the Supabase REST
backend implements.

Business logic never calls the database client directly. In STORAGE_BACKEND=supabase_rest
mode the existing repositories keep calling `get_database()` (which returns the
Motor-compatible `AdapterDatabase`) and the finance repositories; both sit on top
of this interface. Switching back to STORAGE_BACKEND=mongodb_supabase simply
routes the very same repositories to MongoDB/PostgreSQL again - nothing in the
services or the React frontend changes.

All documents crossing this interface are plain Python dicts using native types
(datetime, Decimal, bson.ObjectId); the adapter owns the wire encoding.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageAdapter(ABC):
    """Conceptual operations required by the existing services."""

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def get(self, table: str, id: str, projection: dict | None = None) -> dict | None: ...

    @abstractmethod
    async def find_one(self, table: str, filters: dict | None = None, sort: dict | None = None,
                       projection: dict | None = None) -> dict | None: ...

    @abstractmethod
    async def query(self, table: str, filters: dict | None = None, sort: dict | None = None,
                    skip: int = 0, limit: int = 100, projection: dict | None = None) -> tuple[list[dict], int]:
        """Returns (documents, total_matching)."""

    @abstractmethod
    async def list(self, table: str, filters: dict | None = None, page: int = 1, limit: int = 100) -> tuple[list[dict], dict]: ...

    @abstractmethod
    async def count(self, table: str, filters: dict | None = None) -> int: ...

    @abstractmethod
    async def create(self, table: str, data: dict) -> dict:
        """Raises DuplicateKeyError on a unique-constraint violation."""

    @abstractmethod
    async def batch_create(self, table: str, rows: list[dict]) -> list[dict]: ...

    @abstractmethod
    async def update(self, table: str, id: str | None, update: dict, filters: dict | None = None,
                     many: bool = False) -> dict: ...

    @abstractmethod
    async def batch_update(self, table: str, updates: list[tuple[dict, dict]]) -> int: ...

    @abstractmethod
    async def find_one_and_update(self, table: str, filters: dict, update: dict, upsert: bool = False,
                                  return_after: bool = True, sort: dict | None = None) -> dict | None: ...

    @abstractmethod
    async def delete(self, table: str, id: str | None = None, filters: dict | None = None, many: bool = False) -> int: ...

    @abstractmethod
    async def batch(self, operations: list[dict]) -> list[Any]:
        """Runs the operations in order under ONE write lock (all-or-report)."""

    @abstractmethod
    async def sum(self, table: str, field: str | None, filters: dict | None = None,
                  group_by: list[str] | None = None) -> dict: ...

    @abstractmethod
    async def ledger_summary(self, filters: dict | None = None) -> dict: ...
