# Third-Party Notices

draft2craift is released under the GNU Affero General Public License v3.0.
This file documents the licenses of all third-party components that are
bundled with or optionally used by draft2craift.

---

## Required Dependencies

### PySide6
- **License:** GNU Lesser General Public License v3.0 (LGPL-3.0) / GPL-2.0-or-later / Qt Commercial
- **Copyright:** Copyright (C) The Qt Company Ltd.
- **Homepage:** https://www.qt.io/
- **License text:** https://www.gnu.org/licenses/lgpl-3.0.txt
- **Notes:** Used as the GUI framework. LGPL-3.0 is compatible with AGPL-3.0.

### llama-cpp-python
- **License:** MIT
- **Copyright:** Copyright (c) 2023 Andrei Betlen
- **Homepage:** https://github.com/abetlen/llama-cpp-python
- **Notes:** Python bindings for llama.cpp (also MIT, Copyright (c) 2023 Georgi Gerganov).

### networkx
- **License:** BSD-3-Clause
- **Copyright:** Copyright (c) 2004-2026, NetworkX Developers
- **Homepage:** https://networkx.org/
- **Notes:** Used for graph topology handling and force-directed layout.

---

## Optional Dependencies — MIT / Apache / BSD Profile

### python-docx
- **License:** MIT
- **Copyright:** Copyright (c) 2013 Steve Canny
- **Homepage:** https://github.com/python-openxml/python-docx

### markdownify
- **License:** MIT
- **Copyright:** Copyright (c) 2019 Matthew Tretter
- **Homepage:** https://github.com/matthewwithanm/python-markdownify

### odfpy
- **License:** Apache-2.0 / GPL-2.0-or-later (dual license; Apache-2.0 path used)
- **Copyright:** Copyright (c) 2008 Søren Roug
- **Homepage:** https://github.com/eea/odfpy

### sentence-transformers
- **License:** Apache-2.0
- **Copyright:** Copyright (c) 2019 UKP Lab
- **Homepage:** https://github.com/UKPLab/sentence-transformers

### PyTorch (torch)
- **License:** BSD-3-Clause
- **Copyright:** Copyright (c) 2016 Facebook, Inc. (Adam Paszke)
- **Homepage:** https://pytorch.org/
- **Notes:** Pulled in transitively by sentence-transformers.

### transformers (Hugging Face)
- **License:** Apache-2.0
- **Copyright:** Copyright (c) 2018 The HuggingFace Inc. team
- **Homepage:** https://github.com/huggingface/transformers
- **Notes:** Pulled in transitively by sentence-transformers.

### scikit-learn
- **License:** BSD-3-Clause
- **Copyright:** Copyright (c) 2007–2024 The scikit-learn developers
- **Homepage:** https://scikit-learn.org/
- **Notes:** Pulled in transitively (TF-IDF RAG).

### NumPy
- **License:** BSD-3-Clause
- **Copyright:** Copyright (c) 2005–2024 NumPy Developers
- **Homepage:** https://numpy.org/

### SciPy
- **License:** BSD-3-Clause
- **Copyright:** Copyright (c) 2001–2002 Enthought Inc., 2003–2024 SciPy Developers
- **Homepage:** https://scipy.org/

### Pillow
- **License:** MIT-CMU / HPND
- **Copyright:** Copyright (c) 1995–2011 Fredrik Lundh; Copyright (c) 1997–2011 Secret Labs AB; Copyright (c) 2010 Alex Clark
- **Homepage:** https://python-pillow.org/

---

## Optional Dependencies — Extended / AGPL Profile

The following packages are **not included** in pre-built binaries.
They can be installed manually by the user. By using them, the user
accepts the respective license terms.

### PyMuPDF (fitz)
- **License:** GNU Affero General Public License v3.0 (AGPL-3.0)
- **Copyright:** Copyright (c) 2012–2024 Artifex Software, Inc.
- **Homepage:** https://pymupdf.readthedocs.io/
- **License text:** https://www.gnu.org/licenses/agpl-3.0.txt

### pymupdf4llm
- **License:** GNU Affero General Public License v3.0 (AGPL-3.0)
- **Copyright:** Copyright (c) 2024 Artifex Software, Inc.
- **Homepage:** https://github.com/pymupdf/RAG

### html2text
- **License:** GNU General Public License v3.0 (GPL-3.0)
- **Copyright:** Copyright (c) 2004 Aaron Swartz; Copyright (c) 2011 Dwayne Litzenberger
- **Homepage:** https://github.com/Alir3z4/html2text

---

## Python Standard Library

The Python standard library is used extensively (os, sys, re, csv, json,
pathlib, threading, dataclasses, etc.) and is governed by the
Python Software Foundation License (PSF-2.0), which is compatible with
AGPL-3.0. See https://docs.python.org/3/license.html.
