# MediScribe AI — Technology Stack

This document enumerates the technologies, frameworks, and libraries utilized across the MediScribe AI codebase, detailing the architectural rationale for each selection. Only tools actively present in the repository are listed.

---

## 1. Backend Runtime & Core Framework

| Technology | Version / Spec | Purpose | Architectural Rationale |
|---|---|---|---|
| **Python** | 3.10+ | Primary backend language | Rich ecosystem for scientific computing, natural language processing, and medical informatics libraries. |
| **FastAPI** | 0.104.1 | Asynchronous REST API framework | High performance (ASGI), native Pydantic v2 data validation, automated OpenAPI documentation generation, and native asynchronous request handling. |
| **Uvicorn** | 0.24.0 | ASGI web server | Production-grade asynchronous web server implementation for Python. |
| **Pydantic** | ≥ 2.0.0 | Request/Response data validation | Strict runtime type-checking, data coercion, serialization, and boundary protection for JSON payloads. |
| **python-dotenv** | 1.0.0 | Environment management | Parses `.env` configuration files to keep sensitive API keys and secrets decoupled from source code. |

---

## 2. Speech-to-Text & Acoustic Processing

| Technology | Version / Spec | Purpose | Architectural Rationale |
|---|---|---|---|
| **faster-whisper** | ≥ 0.9.0 | Local speech-to-text inference | Reimplements OpenAI's Whisper model using CTranslate2, providing up to 4x faster execution and lower memory consumption compared to PyTorch Whisper. Runs entirely on-premise, ensuring clinical audio never leaves the host server. |
| **FFmpeg** | Binary dependency | Audio transcoding and normalization | Industry-standard audio processing utility for unpacking, decoding, and converting varied clinical recording formats (.mp3, .wav, .m4a, .webm) into raw PCM streams. |

---

## 3. Biomedical Natural Language Processing

| Technology | Version / Spec | Purpose | Architectural Rationale |
|---|---|---|---|
| **spaCy** | ≥ 3.7.0 | Base linguistic engine | Industrial-strength NLP library providing fast tokenization, sentence segmentation, dependency parsing, and POS tagging. |
| **scispaCy (`en_ner_bc5cdr_md`)** | ≥ 0.5.4 | Specialized biomedical Named Entity Recognition | Pretrained on the BC5CDR corpus specifically for identifying clinical entities (chemicals, drugs, and diseases) with high precision in medical literature and notes. |
| **medspaCy** | ≥ 1.0.0 | Contextual assertion analysis | Implements the ConText algorithm to identify clinical assertions such as negation ("no history of..."), uncertainty ("suspected..."), temporality ("previous..."), and experiencer ("mother had..."). |
| **rapidfuzz** | 3.6.1 | Fuzzy string matching and evidence alignment | High-performance C++ accelerated string similarity matching used by the evidence-linking service to trace SOAP claims back to transcript sentences. |

---

## 4. Large Language Model (LLM) Integration

| Technology | Version / Spec | Purpose | Architectural Rationale |
|---|---|---|---|
| **Groq Python SDK** | ≥ 0.9.0 | LLM API client | Low-latency cloud inference interface connecting to LPU hardware. Selected for fast response times in clinical environments. |
| **LLaMA 3.3 70B Versatile** | Cloud Model (`llama-3.3-70b-versatile`) | Clinical SOAP note synthesis | Open-weight foundation model offering clinical reasoning capabilities, zero-shot structured JSON compliance, and prompt adherence. |

---

## 5. Persistence & Data Storage

| Technology | Version / Spec | Purpose | Architectural Rationale |
|---|---|---|---|
| **SQLAlchemy** | 2.0.23 | Object-Relational Mapping (ORM) | Type-safe SQL abstraction providing declarative models, connection pooling, and cross-database portability. |
| **Alembic** | 1.13.1 | Database schema migrations | Declarative, version-controlled schema evolution ensuring reproducible database structure across development and production. |
| **SQLite** | Standard library | Development and test database | Zero-configuration, serverless, self-contained SQL database engine enabling in-memory test suites and lightweight local development. |
| **PostgreSQL** *(Optional / Production)* | ≥ 15 (psycopg2-binary 2.9.9) | Production relational database | Enterprise-grade ACID compliance, concurrent read/write transactions, relational integrity, and scalability for multi-user hospital deployments. |

---

## 6. Security & Authentication

| Technology | Version / Spec | Purpose | Architectural Rationale |
|---|---|---|---|
| **python-jose[cryptography]** | 3.3.0 | JSON Web Token (JWT) encoding & validation | Stateless session verification using standard HS256 signatures for API authentication. |
| **passlib[bcrypt] & bcrypt** | passlib 1.7.4, bcrypt 4.0.1 | Password hashing | Cryptographically secure, salted, one-way password hashing adhering to OWASP authentication standards. |

---

## 7. Frontend Architecture

| Technology | Version / Spec | Purpose | Architectural Rationale |
|---|---|---|---|
| **React** | 19.2.0 | Declarative UI framework | Component-based view layer utilizing React 19 hooks and concurrent rendering for smooth UI transitions during audio playback and note editing. |
| **TypeScript** | ~5.8.3 | Static type safety | Eliminates runtime type errors, guarantees API contract adherence via shared interfaces, and enhances developer maintainability. |
| **Vite** | 7.3.1 | Build tool and dev server | Sub-second Hot Module Replacement (HMR) and optimized ES module bundling. |
| **React Router** | 7.18.4 | Client-side routing | Declarative routing managing clinician navigation across dashboard, consultation flows, history, and settings. |
| **Zustand** | 5.0.11 | Client state management | Minimalist, unopinionated state management store with zero boilerplate, used for managing active consultation drafts and session tokens. |
| **Tailwind CSS** | v4.2.0 | Utility-first styling | Modern utility-first CSS engine enabling responsive layouts, dark mode support, and cohesive design tokens. |
| **Axios** | 1.13.5 | Promise-based HTTP client | Configured with automatic authorization header injection, request interceptors, and error handling. |
| **Lucide React** | 0.575.0 | Iconography | Lightweight, accessible SVG icon set. |
| **Sonner** | 2.0.7 | Toast notifications | Non-blocking clinical alerts, error notices, and auto-dismissing status feedback. |

---

## 8. Testing & Quality Assurance

| Technology | Version / Spec | Purpose | Architectural Rationale |
|---|---|---|---|
| **pytest** | ≥ 8.0 | Backend unit and integration test runner | Python test framework supporting fixtures, parameterized testing, and clean assertions. |
| **httpx** | Standard test dependency | Asynchronous HTTP test client | Simulates client API requests against FastAPI application instances without requiring network socket binding. |

---

## 9. Optional and Planned Technologies

| Technology | Category | Status | Role |
|---|---|---|---|
| **PostgreSQL** | Database | Implemented (Optional) | Default development setup runs SQLite (`DATABASE_URL=sqlite:///./mediscribe_dev.db`). PostgreSQL is containerized and available via Docker Compose for production. |
| **PyAnnote Audio** | Audio Processing | Planned | Neural speaker diarization to split multi-party clinical dialogue into doctor/patient conversation turns. |
| **HL7 FHIR API (HAPI FHIR / Medplum)** | Integration | Planned | Standardized clinical data exchange to push approved SOAP notes directly to Epic, Cerner, or open-source EHRs. |
