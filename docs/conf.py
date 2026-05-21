from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath("../src"))

docs_dir = Path(__file__).resolve().parent
matplotlib_config_dir = docs_dir / "_build" / ".matplotlib"
matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config_dir))
os.environ.setdefault("DYNA_SCHEDBENCH_DISABLE_DOTENV", "1")

project = "DynaSchedBench"
author = "DynaSchedBench contributors"
copyright = f"{datetime.now().year}, {author}"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx_autodoc_typehints",
]

autosummary_generate = True
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "superpowers/**"]
autodoc_member_order = "bysource"
autodoc_typehints = "description"
napoleon_google_docstring = True
napoleon_numpy_docstring = True

html_theme = "sphinx_rtd_theme"
html_title = "DynaSchedBench"
