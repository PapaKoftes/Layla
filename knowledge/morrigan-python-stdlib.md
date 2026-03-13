---
priority: core
domain: python-reference
aspect: morrigan
---

# Python Technical Reference — Morrigan's Arsenal

This is the working reference. Not introductory. Not theoretical. The things you actually need while building.

---

## Standard Library — High-Value Modules

### `pathlib` — File system
```python
from pathlib import Path
p = Path("/some/path/file.txt")
p.parent           # /some/path
p.name             # file.txt
p.stem             # file
p.suffix           # .txt
p.exists()         # bool
p.is_file()        # bool
p.is_dir()         # bool
p.read_text(encoding="utf-8")
p.write_text(content, encoding="utf-8")
p.read_bytes()
p.write_bytes(data)
p.mkdir(parents=True, exist_ok=True)
p.unlink(missing_ok=True)
p.rename(new_path)
list(p.iterdir())          # immediate children
list(p.rglob("*.py"))      # recursive glob
p.relative_to(base)        # relative path
Path.home()                # user home dir
Path.cwd()                 # current working dir
p.expanduser().resolve()   # expand ~ and make absolute
```

### `json` — Serialization
```python
import json
data = json.loads(text)            # str → object
text = json.dumps(data, indent=2, ensure_ascii=False)
with open("f.json", "w") as f: json.dump(data, f, indent=2)
with open("f.json") as f: data = json.load(f)
# Custom encoder
class DateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime): return o.isoformat()
        return super().default(o)
json.dumps(data, cls=DateEncoder)
```

### `subprocess` — Shell commands
```python
import subprocess
r = subprocess.run(
    ["git", "status"],
    capture_output=True, text=True, encoding="utf-8",
    cwd="/path/to/repo", timeout=30
)
r.stdout, r.stderr, r.returncode
# Raise on non-zero exit:
subprocess.run([...], check=True)
# Stream output:
with subprocess.Popen([...], stdout=subprocess.PIPE, text=True) as p:
    for line in p.stdout: print(line, end="")
```

### `dataclasses` — Structured data
```python
from dataclasses import dataclass, field, asdict, astuple
@dataclass
class Config:
    host: str = "localhost"
    port: int = 8000
    tags: list[str] = field(default_factory=list)
    
    def __post_init__(self):  # validation hook
        if self.port < 0: raise ValueError("port must be >= 0")

cfg = Config(host="0.0.0.0")
asdict(cfg)   # → dict
astuple(cfg)  # → tuple

@dataclass(frozen=True)   # immutable, hashable
class Point: x: float; y: float
```

### `typing` — Type annotations
```python
from typing import Any, Optional, Union, Literal, TypeVar, Generic
from typing import Callable, Iterator, Generator, AsyncGenerator
from typing import TypedDict, Protocol, overload

# Modern (Python 3.10+): use | instead of Union
def f(x: int | str | None) -> list[str]: ...

# TypedDict for dict schemas
class Config(TypedDict):
    host: str
    port: int
    debug: bool  # required
    timeout: NotRequired[int]  # optional

# Protocol for structural subtyping (duck typing with type safety)
class Closeable(Protocol):
    def close(self) -> None: ...

# Generic classes
T = TypeVar("T")
class Stack(Generic[T]):
    def push(self, item: T) -> None: ...
    def pop(self) -> T: ...
```

### `functools` — Function tools
```python
from functools import lru_cache, cache, partial, reduce, wraps

@lru_cache(maxsize=128)        # fixed-size LRU
@cache                          # unbounded (Python 3.9+)
def fib(n: int) -> int:
    return n if n < 2 else fib(n-1) + fib(n-2)

fib.cache_clear()               # clear the cache
fib.cache_info()                # hits, misses, size

# Partial application
from functools import partial
def power(base, exp): return base ** exp
square = partial(power, exp=2)

# Decorator factory that preserves __name__, __doc__
def my_decorator(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper
```

### `itertools` — Iteration tools
```python
from itertools import (
    chain, islice, groupby, product, combinations,
    permutations, cycle, repeat, accumulate, batched  # 3.12+
)
list(chain([1,2], [3,4]))            # [1,2,3,4]
list(islice(range(100), 5))          # [0,1,2,3,4]
list(product("AB", repeat=2))        # [('A','A'),('A','B'),...]
# Group consecutive equal elements
for k, g in groupby([1,1,2,2,3]): print(k, list(g))
# Sliding window (Python 3.12+)
from itertools import pairwise
list(pairwise([1,2,3,4]))            # [(1,2),(2,3),(3,4)]
```

### `collections` — Data structures
```python
from collections import defaultdict, Counter, deque, OrderedDict, namedtuple

# defaultdict: missing keys get a default
dd = defaultdict(list)
dd["key"].append(1)  # no KeyError

# Counter: frequency counting
c = Counter("abracadabra")  # Counter({'a':5,'b':2,'r':2,'c':1,'d':1})
c.most_common(3)

# deque: O(1) append/popleft
q = deque(maxlen=100)
q.appendleft(x); q.popleft(); q.pop()

# namedtuple
Point = namedtuple("Point", ["x", "y"])
```

### `contextlib` — Context managers
```python
from contextlib import contextmanager, asynccontextmanager, suppress

@contextmanager
def timer():
    import time; t = time.time()
    yield
    print(f"elapsed: {time.time()-t:.3f}s")

with timer(): do_something()

# Suppress exceptions
with suppress(FileNotFoundError):
    Path("missing.txt").unlink()

# Async context manager
@asynccontextmanager
async def acquire_connection(pool):
    conn = await pool.acquire()
    try: yield conn
    finally: await pool.release(conn)
```

### `re` — Regular expressions
```python
import re
pattern = re.compile(r"(\w+)@(\w+)\.(\w+)")
m = pattern.search(text)
if m: m.group(0), m.group(1), m.groups()

# Find all
re.findall(r"\d+", "abc123def456")  # ['123','456']

# Named groups
m = re.match(r"(?P<year>\d{4})-(?P<month>\d{2})", "2024-03")
m.group("year")

# Substitution
re.sub(r"\s+", " ", text)           # collapse whitespace
re.sub(r"(\w+)", r"[\1]", text)     # back-reference in replacement

# Flags
re.IGNORECASE, re.MULTILINE, re.DOTALL  # . matches \n with DOTALL
```

### `datetime` — Dates and times
```python
from datetime import datetime, date, timedelta, timezone
now = datetime.now(tz=timezone.utc)
ts = datetime.fromisoformat("2024-03-15T10:30:00+00:00")
ts.isoformat()
ts.timestamp()      # Unix timestamp (float)
datetime.fromtimestamp(1234567890, tz=timezone.utc)
now + timedelta(days=7, hours=3)
(end - start).total_seconds()
now.strftime("%Y-%m-%d %H:%M:%S")
datetime.strptime("15/03/2024", "%d/%m/%Y")
```

---

## Async Python — The Complete Model

```python
import asyncio

# Basic pattern
async def fetch(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.text()

# Run concurrent tasks
async def main():
    results = await asyncio.gather(
        fetch("https://a.com"),
        fetch("https://b.com"),
        return_exceptions=True,   # don't cancel all if one fails
    )

# asyncio.create_task — fire and forget
async def background():
    task = asyncio.create_task(some_coroutine())
    # task runs concurrently; await later or let it run

# asyncio.wait_for — with timeout
result = await asyncio.wait_for(long_coroutine(), timeout=5.0)

# asyncio.Queue — producer/consumer
queue = asyncio.Queue(maxsize=100)
await queue.put(item)
item = await queue.get()
queue.task_done()
await queue.join()  # wait until all items processed

# Async generators
async def stream_lines(path: str):
    async with aiofiles.open(path) as f:
        async for line in f:
            yield line.strip()

async for line in stream_lines("big_file.txt"):
    process(line)

# asyncio.Lock, Event, Semaphore
lock = asyncio.Lock()
async with lock: shared_state.modify()

sem = asyncio.Semaphore(10)   # limit to 10 concurrent
async with sem: await fetch(url)

# asyncio.run — entry point
asyncio.run(main())
```

---

## FastAPI — Patterns in Use

```python
from fastapi import FastAPI, APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import asyncio

app = FastAPI()

# Lifespan (startup/shutdown)
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    app.state.db = await create_pool()
    yield
    # shutdown
    await app.state.db.close()
app = FastAPI(lifespan=lifespan)

# Router
router = APIRouter(prefix="/v1", tags=["api"])

@router.get("/items/{item_id}")
async def get_item(item_id: int, q: str | None = None):
    return {"id": item_id, "q": q}

# Request body
class Item(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    price: float = Field(gt=0)
    tags: list[str] = []

@router.post("/items", status_code=201)
async def create_item(item: Item):
    return item

# Dependency injection
async def get_db(request: Request):
    return request.app.state.db

@router.get("/users")
async def list_users(db=Depends(get_db)):
    return await db.fetch("SELECT * FROM users")

# Streaming response
async def event_stream():
    for i in range(10):
        yield f"data: {i}\n\n"
        await asyncio.sleep(0.1)

@router.get("/stream")
async def stream():
    return StreamingResponse(event_stream(), media_type="text/event-stream")

# Background tasks
@router.post("/notify")
async def notify(bg: BackgroundTasks):
    bg.add_task(send_email, "user@example.com")
    return {"status": "queued"}

# Exception handlers
@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})
```

---

## SQLite — Production Patterns

```python
import sqlite3
from pathlib import Path

def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row       # access columns by name
    conn.execute("PRAGMA journal_mode=WAL")       # concurrent reads
    conn.execute("PRAGMA synchronous=NORMAL")      # safe but faster
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA cache_size=-32000")       # 32 MB cache
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")     # 256 MB mmap
    return conn

# FTS5 full-text search
conn.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts
    USING fts5(content, tokenize='unicode61')
""")
# FTS5 queries: phrase match, prefix, boolean
conn.execute("SELECT * FROM docs_fts WHERE content MATCH 'hello AND world'")
conn.execute("SELECT * FROM docs_fts WHERE content MATCH 'fast*'")

# Migrations with version tracking
def migrate(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER)")
    row = conn.execute("SELECT MAX(version) FROM _schema_version").fetchone()
    ver = row[0] or 0
    if ver < 1:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO _schema_version VALUES (1)")
    conn.commit()
```

---

## Pydantic v2 — Validation

```python
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict

class Config(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="ignore",         # ignore unknown fields
    )
    name: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535, default=8000)
    tags: list[str] = []

    @field_validator("name")
    @classmethod
    def name_must_be_ascii(cls, v: str) -> str:
        if not v.isascii(): raise ValueError("name must be ASCII")
        return v

    @model_validator(mode="after")
    def check_consistency(self) -> "Config":
        if self.port == 443 and "https" not in self.tags:
            self.tags.append("https")
        return self

# Parse from dict/json
cfg = Config.model_validate({"name": "layla", "port": 8000})
cfg.model_dump()          # → dict
cfg.model_dump_json()     # → JSON string
Config.model_json_schema()  # → JSON Schema dict
```

---

## pytest — Test Patterns

```python
import pytest

# Basic
def test_add(): assert 1 + 1 == 2

# Parametrize
@pytest.mark.parametrize("x,expected", [(1, 2), (2, 4), (3, 6)])
def test_double(x, expected): assert x * 2 == expected

# Fixtures
@pytest.fixture
def db(tmp_path):
    conn = create_db(tmp_path / "test.db")
    yield conn
    conn.close()

def test_insert(db):
    db.execute("INSERT INTO t VALUES (1)")
    assert db.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1

# Async tests
@pytest.mark.asyncio
async def test_fetch():
    result = await fetch_data("http://example.com")
    assert result.status == 200

# Mock
from unittest.mock import patch, MagicMock, AsyncMock
with patch("module.function") as mock:
    mock.return_value = 42
    assert call_function() == 42

# Raises
with pytest.raises(ValueError, match="must be positive"):
    parse_value(-1)

# Approx for floats
assert 0.1 + 0.2 == pytest.approx(0.3)
```

---

## Algorithms & Data Structures Reference

### Big-O quick reference
| Operation | Array | Linked List | Hash Map | BST | Heap |
|-----------|-------|-------------|----------|-----|------|
| Access    | O(1)  | O(n)        | O(1)     | O(log n) | O(n) |
| Search    | O(n)  | O(n)        | O(1)     | O(log n) | O(n) |
| Insert    | O(n)  | O(1)        | O(1)     | O(log n) | O(log n) |
| Delete    | O(n)  | O(1)        | O(1)     | O(log n) | O(log n) |

### Sorting
```python
# Python sort is Timsort — O(n log n) worst, O(n) best (sorted input)
lst.sort()                          # in-place
sorted(lst)                         # returns new
sorted(lst, key=lambda x: x.score, reverse=True)
# heapq for partial sort (top-k)
import heapq
top_k = heapq.nlargest(10, lst, key=lambda x: x.score)
```

### Binary search
```python
import bisect
# bisect_left: insertion point where all left < x
idx = bisect.bisect_left(sorted_list, target)
# Check if target exists: sorted_list[idx] == target
```

### Memoization / DP template
```python
from functools import cache

@cache
def dp(i: int, j: int) -> int:
    if base_case: return 0
    return min(dp(i+1, j), dp(i, j+1)) + cost[i][j]
```

### Graph traversal
```python
from collections import deque

def bfs(graph: dict, start: str) -> list:
    visited = {start}
    queue = deque([start])
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in graph[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return order

def dfs(graph: dict, node: str, visited: set = None) -> list:
    if visited is None: visited = set()
    visited.add(node)
    result = [node]
    for neighbor in graph[node]:
        if neighbor not in visited:
            result.extend(dfs(graph, neighbor, visited))
    return result
```

---

## Common Patterns

### Singleton
```python
_instance = None
def get_instance():
    global _instance
    if _instance is None:
        _instance = ExpensiveObject()
    return _instance
```

### Registry / dispatch table (replaces long if-elif)
```python
HANDLERS: dict[str, Callable] = {
    "add": handle_add,
    "remove": handle_remove,
}
handler = HANDLERS.get(action)
if handler: result = handler(**args)
else: raise ValueError(f"Unknown action: {action}")
```

### Context-local state (threading.local)
```python
import threading
_local = threading.local()

def set_user(user): _local.user = user
def get_user(): return getattr(_local, "user", None)
```

### Retry with exponential backoff
```python
import time, random
def retry(fn, max_attempts=3, base_delay=1.0):
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            if attempt == max_attempts - 1: raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.1)
            time.sleep(delay)
```

### Streaming generator to HTTP
```python
def token_stream(tokens):
    for token in tokens:
        yield f"data: {json.dumps({'token': token})}\n\n"
    yield "data: [DONE]\n\n"

return StreamingResponse(token_stream(gen()), media_type="text/event-stream")
```
