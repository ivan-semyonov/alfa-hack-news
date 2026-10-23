# Third-party notices — 1.0.0

Versions are pinned in `backend/requirements-lock.txt`. Licenses below are read from the installed distributions' metadata, not inferred from package names. Upstream license texts for the installed Python distributions are collected in `THIRD_PARTY_LICENSES/`; their notices remain authoritative.

| Component | Version | Declared license |
|---|---|---|
| Python | 3.12 runtime | PSF |
| FastAPI | 0.128.2 | MIT |
| Pydantic | 2.13.5 | MIT |
| NetworkX | 3.6.1 | BSD-3-Clause |
| Uvicorn | 0.48.0 | BSD-3-Clause |
| HTTPX | 0.28.1 | BSD-3-Clause |
| pypdf | 6.21.2 | BSD-3-Clause |
| psycopg / psycopg-binary | 3.3.6 | LGPL-3.0-only |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| cryptography | 46.0.7 | Apache-2.0 OR BSD-3-Clause |
| Pillow | 12.3.0 | MIT-CMU |
| cffi | 2.1.1 | MIT-0 |
| pycparser | 3.12 | BSD-3-Clause |
| pytest (development) | 9.0.2 | MIT |

Transitive dependency notices are also collected. Binary wheels can bundle additional libraries; consult their included licenses. Python and installed OS utilities are not copied into the source ZIP. Docker installs Poppler and Tesseract from Debian packages; those packages supply their own copyright/license files in the image. Container redistribution must retain those notices. Windows OCR is an operating system facility, not bundled application code.

The industry templates and UI are project-authored. APQC PCF and ASCM SCOR are methodological references only: no proprietary full process frameworks are embedded. No model weights, external AI agents or embedding models are distributed. LLM model access is subject to the provider's terms and the six-model allowlist from the supplied specification.

Bank CSV, analytical PDFs, API keys, private extracted text and actual banking records are excluded from source releases. Demo companies, news and analytical snippets are explicitly synthetic. A local bank PDF was used only for private OCR/RAG acceptance, without inclusion in the release. The project owner's license for the original application code is not assigned automatically by this notice.
