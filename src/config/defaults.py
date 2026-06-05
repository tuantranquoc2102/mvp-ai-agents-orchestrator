"""Shared constants used across api/scope, agents, workflow.

Kept in one module so language sets / skip lists / prompts can be tweaked
without hunting through the codebase.
"""
from __future__ import annotations


# --------------------------------------------------------------------------- walker

# Directories we never descend into when walking a codebase.
SKIP_DIRS: set[str] = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", "target", "out", ".idea", ".vscode", ".next",
    ".nuxt", ".cache", "coverage", ".tox",
}

# Extra skips for this tool's own artifact dirs (so running the analyzer on
# its own repo doesn't surface prior runs' output/.checkpoint as "matches").
SCOPE_SKIP_DIRS: set[str] = SKIP_DIRS | {"output", ".checkpoints", ".agent_cache"}

# Map common extensions to a language label for the inventory step.
EXT_TO_LANG: dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".cs": "C#", ".fs": "F#", ".vb": "VB.NET",
    ".c": "C", ".h": "C/C++ header", ".hpp": "C++ header",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++",
    ".m": "Objective-C", ".mm": "Objective-C++",
    ".swift": "Swift", ".dart": "Dart",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".ps1": "PowerShell", ".bat": "Batch", ".cmd": "Batch",
    ".sql": "SQL", ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".vue": "Vue", ".svelte": "Svelte",
    ".jsp": "JSP",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
    ".xml": "XML", ".md": "Markdown", ".rst": "reStructuredText",
    ".lua": "Lua", ".r": "R", ".jl": "Julia", ".ex": "Elixir",
    ".exs": "Elixir", ".erl": "Erlang", ".clj": "Clojure",
    ".hs": "Haskell", ".elm": "Elm", ".nim": "Nim", ".zig": "Zig",
    ".dockerfile": "Dockerfile",
}


# --------------------------------------------------------------------------- feature scope

# Defaults sized so a typical endpoint sweep stays well under any prompt-
# cache budget while still giving the LLM enough code to reason about.
FEATURE_DEFAULTS: dict[str, int] = {
    "max_files": 30,           # cap matched files
    "full_content_kb": 30,     # files smaller than this go in full
    "context_lines": 8,        # excerpt window around each match
    "max_matches_per_file": 12,
}

# Skip files that are obviously not source code even if they happen to
# mention the query string (build artifacts, lockfiles, binary blobs).
BINARY_OR_NOISE_EXTS: set[str] = {
    ".lock", ".min.js", ".min.css", ".map", ".pyc", ".pyo", ".class",
    ".jar", ".war", ".dll", ".so", ".dylib", ".exe", ".bin", ".o",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar",
    ".gz", ".bz2", ".7z", ".woff", ".woff2", ".ttf", ".eot",
}

# When restricting feature search to source code (the default), only these
# extensions and file names are considered. Anything else (JSON, YAML, MD,
# TOML, XML, ...) is excluded unless --include-non-source is passed.
SOURCE_EXTS: set[str] = {
    ".py", ".pyi",
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".java", ".kt", ".scala", ".groovy",
    ".go", ".rs", ".rb", ".php", ".dart", ".swift",
    ".cs", ".fs", ".vb",
    ".c", ".h", ".hpp", ".cc", ".cpp", ".cxx", ".m", ".mm",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".sql",
    ".html", ".htm", ".jsp", ".vue", ".svelte",
    ".css", ".scss", ".sass", ".less",
    ".lua", ".r", ".jl", ".ex", ".exs", ".erl",
    ".clj", ".cljs", ".hs", ".elm", ".nim", ".zig",
}
SOURCE_FILE_NAMES: set[str] = {"Dockerfile", "Makefile", "Rakefile", "Gemfile"}


# --------------------------------------------------------------------------- symbol expansion

# Names so common they'd flood 2-hop discovery results with false positives.
SYMBOL_SKIP: set[str] = {
    # Go stdlib packages
    "fmt", "os", "io", "net", "http", "time", "context", "errors", "log",
    "strings", "strconv", "bytes", "sync", "sort", "reflect", "json",
    "regexp", "math", "crypto", "encoding", "bufio", "path", "filepath",
    "url", "rand", "tls", "x509", "ioutil", "atomic", "rune",
    # Python stdlib
    "sys", "re", "typing", "datetime", "pathlib", "logging", "collections",
    "functools", "itertools", "asyncio", "subprocess", "argparse",
    # JS/TS globals
    "console", "process", "Buffer", "JSON", "Object", "Array", "String",
    "Number", "Promise", "Math", "Date", "Error", "Map", "Set", "Symbol",
    # Generic keywords / types
    "true", "false", "null", "nil", "self", "this", "string", "int", "bool",
    "float", "void", "var", "let", "const", "func", "return", "type",
    "package", "import", "from", "as", "def", "lambda", "interface",
    "struct", "class", "Test", "Mock", "Setup", "TearDown",
    # Generic verb / noun names (especially in Go/ORM code) — too common
    # to expand on; they'd pull in unrelated files via word-boundary match.
    "Get", "Set", "Add", "Remove", "Update", "Delete", "Create", "Find",
    "Insert", "Upsert", "Query", "Where", "Select", "Scan", "Wrap", "Use",
    "New", "Make", "Build", "Run", "Call", "Read", "Write", "Open", "Close",
    "Parse", "Format", "Print", "Println", "Marshal", "Unmarshal",
    "Encode", "Decode", "Hash", "Sign", "Verify",
    "Handler", "Middleware", "Router", "Request", "Response", "Context",
    "Result", "Status", "Config", "Options", "Client", "Server", "Service",
    "Manager", "Builder", "Factory", "Repository", "Controller",
    "Logger", "Tracer", "Metric", "Counter", "Gauge",
    "Bytes", "Time", "Duration", "Buffer", "Reader", "Writer", "Closer",
    "Filter", "Mapper", "Adapter", "Wrapper",
}


# --------------------------------------------------------------------------- prompts

# Asked to the architect agent when --mermaid is enabled.
DIAGRAM_INSTRUCTION: str = (
    "Produce ONE Mermaid flowchart that captures the ACTUAL BUSINESS LOGIC "
    "of the endpoint as observed in the source code provided.\n\n"
    "This is NOT an architecture diagram. The reader should learn from this "
    "diagram what happens when a request comes in: which checks run, which "
    "branches the code takes, which services are called and under what "
    "conditions, and what is returned.\n\n"
    "The diagram MUST:\n"
    "1. Start at the incoming HTTP request, end at the response(s).\n"
    "2. Show EVERY conditional branch (if/else/switch/match/guard) that "
    "routes to different services, returns different responses, or applies "
    "different logic. Use diamond `{...}` nodes for conditions. Label BOTH "
    "outgoing edges with what triggers them (e.g. `flag = 1` / `flag = 0`, "
    "`role admin` / `role user`).\n"
    "3. Identify external service calls EXPLICITLY by their real name from "
    "the code (e.g. `YCS API`, `Profile API`, `SAP Backend`, `Auth0`, "
    "`PostgreSQL users table`). Use cylinder `[(External: NAME)]` for "
    "datastores, `[NAME API]` for HTTP services.\n"
    "4. Reflect the call chain: controller -> service method -> downstream "
    "call. If a service method has internal branching, show that branching.\n"
    "5. Show error / 4xx / 5xx response paths as distinct end nodes.\n\n"
    "Example shape (illustrative — match the actual code, not this template):\n"
    "  Request --> Controller --> Cond1{flag == 1?}\n"
    "  Cond1 -->|yes| YCS[YCS API]\n"
    "  Cond1 -->|no| Profile[Profile API]\n"
    "  YCS --> AggregateResponse\n"
    "  Profile --> AggregateResponse\n"
    "  AggregateResponse --> Resp200[/200 JSON/]\n\n"
    "Mermaid syntax rules you MUST follow:\n"
    "- Inside edge labels (the `|...|` between arrows) do NOT use `[`, `]`, "
    "`(`, `)`, `{`, `}` — Mermaid's parser treats them as node shapes. "
    "Rephrase the label in plain words.\n"
    "- Use `<br/>` for line breaks inside labels, never raw newlines.\n"
    "- Keep node IDs simple ASCII (letters, digits, underscore).\n\n"
    "Return ONLY the Mermaid block — fenced as ```mermaid ... ``` — and "
    "no surrounding prose, headings, or commentary."
)
