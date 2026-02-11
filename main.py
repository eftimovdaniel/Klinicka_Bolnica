# Root-level main.py за Render deployment
# Овој фајл го ре-експортира app од backend.main за да работи со uvicorn main:app
import sys
import os
import importlib.util

# Додади backend директориумот во Python path за да работат релативните импорти
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Промени работи директориум на backend за да работат релативните импорти
original_cwd = os.getcwd()
os.chdir(backend_path)

try:
    # Користи importlib за да го импортираме backend/main.py како модул без circular import
    spec = importlib.util.spec_from_file_location(
        "backend_main_module",
        os.path.join(backend_path, "main.py")
    )
    backend_main = importlib.util.module_from_spec(spec)
    # Додади го во sys.modules со уникатно име за да не се конфликтира со 'main'
    sys.modules["backend_main_module"] = backend_main
    spec.loader.exec_module(backend_main)
    app = backend_main.app
finally:
    # Врати го оригиналниот работи директориум
    os.chdir(original_cwd)

__all__ = ["app"]
