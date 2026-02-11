# Root-level main.py за Render deployment
# Овој фајл го ре-експортира app од backend.main за да работи со uvicorn main:app
import sys
import os

# Додади backend директориумот во Python path за да работат релативните импорти
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Промени работи директориум на backend за да работат релативните импорти
original_cwd = os.getcwd()
os.chdir(backend_path)

try:
    # Импортирај main модулот од backend директориумот
    import main as backend_main
    app = backend_main.app
finally:
    # Врати го оригиналниот работи директориум
    os.chdir(original_cwd)

__all__ = ["app"]
