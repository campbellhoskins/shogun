import sys

# Fix Windows console encoding: cp1252 can't handle unicode characters (→, ✓, —)
# that LLMs frequently output. This makes every print() call safe project-wide.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
