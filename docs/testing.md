# MediScribe AI — Testing & Verification Guide

This document describes the testing architecture, test suites, execution commands, mocking strategies, and verified test results for MediScribe AI.

---

## 1. Test Suite Summary

The backend utilizes `pytest` with in-memory SQLite isolation, mocked machine learning pipelines, and stubbed third-party API clients. This ensures fast, repeatable, and completely deterministic execution without requiring GPUs, network connectivity, or external API credits.

### Verified Test Run
- **Total Tests**: 302 collected
- **Passed**: 292
- **Skipped**: 10 (eval/long-running integration tests skipped by default)
- **Duration**: ~20 to 22 seconds
- **Pass Rate**: 100% of non-skipped tests

---

## 2. Test Execution Commands

### Running Backend Unit & Integration Tests
```bash
# Navigate to the backend directory
cd backend

# Execute all tests with concise reporting
python -m pytest tests/ -q

# Run with verbose output and line-by-line test names
python -m pytest tests/ -v

# Run a specific test module
python -m pytest tests/test_consultations.py -v

# Run with coverage report
python -m pytest tests/ --cov=. --cov-report=term-missing
```

### Running Frontend Validation
```bash
# Navigate to the frontend directory
cd frontend

# Verify TypeScript compilation and type safety
npm run build
```

---

## 3. Test Modules & Functional Scope

The test suite consists of 23 test modules organized by architectural boundary:

| Test Module | Scope & Key Behaviors Tested |
|---|---|
| `test_auth.py` | User registration, login, JWT issuance, token expiration, password validation, protected route access guards. |
| `test_consultations.py` | Full multi-step consultation lifecycle: upload, transcription trigger, manual transcript editing, entity extraction, SOAP generation, approval, audio deletion, and error states. |
| `test_evidence_linking.py` | Statement-to-transcript sentence alignment, string similarity thresholds, handling of supported, unsupported, conflicting, and ambiguous evidence. |
| `test_soap_generation_service.py` | Groq API prompt formatting, structured JSON output validation, non-fabrication of vitals, rule-based fallback activation, error handling (rate limits, timeouts). |
| `test_groq_client.py` | Groq client wrapper, retry logic, error class mappings (`MissingApiKeyError`, `GroqRateLimitError`, `GroqTimeoutError`, `GroqConnectionError`). |
| `test_medical_nlp_service.py` | Biomedical NER span detection, entity classification (SYMPTOM, MEDICATION, etc.), confidence score propagation. |
| `test_clinical_assertions.py` | Assertion detection via medspaCy: negation handling ("denies nausea"), uncertainty markers, familial attribution, and temporal qualifiers. |
| `test_content_validator.py` | Gatekeeping against non-clinical content: medical keyword density scoring, marker presence detection, rejection of non-medical recordings. |
| `test_upload_validation.py` | Audio intake validation: accepted file extensions (`.wav`, `.mp3`, `.m4a`, `.ogg`, `.webm`), rejection of unsupported types (`.exe`, `.txt`), 50MB file size limits. |
| `test_history_ownership.py` | Multi-tenant user data isolation: verifies that clinicians cannot access, modify, or delete another user's consultations. |
| `test_transcription_service.py` | Thread-safe singleton instantiation, lazy initialization, audio duration calculations, segment generation, mock audio handling. |
| `test_transcribe_flow.py` | Monolithic `POST /api/transcribe` end-to-end integration, verifying immediate audio cleanup in `finally` blocks. |
| `test_ontology.py` | Mapping clinical terms to RxNorm and ICD-10 identifiers via simulated lookup tables. |
| `test_claim_verification.py` | Verifying claims in generated SOAP notes against transcript facts to prevent hallucinations. |
| `test_clinical_facts.py` | Parsing, storing, and validating discrete factual claims extracted from consultation dialogue. |
| `test_transcript_facts.py` | Sentence segmentation, token mapping, and fact-to-segment traceability. |
| `test_soap_sections.py` | Integrity of individual Subjective, Objective, Assessment, and Plan section boundaries. |
| `test_spell_correction.py` | Clinical lexicon lookup and medical spell-check validation. |
| `test_decoder_vocabulary.py` | Custom acoustic model vocabulary and clinical term recognition. |
| `test_documentation_style.py` | Compliance with clinical documentation formats and standard medical abbreviations. |
| `test_coverage_metric.py` | Evaluation metrics measuring entity coverage between transcripts and generated SOAP notes. |
| `test_eval_metrics.py` | Benchmark evaluation metrics (ROUGE-L, entity recall, assertion precision). |
| `test_eval_data_sources.py` | Synthetic dataset loader testing and benchmark evaluation harness. |

---

## 4. Test Isolation & Mocking Strategy (`conftest.py`)

To ensure tests execute rapidly and deterministically without external hardware or network dependencies, `tests/conftest.py` configures global stubs:

1. **In-Memory SQLite Engine**:
   - Every test runs against a clean SQLite database in memory using SQLAlchemy declarative models.
   - Foreign key constraints are enforced via `PRAGMA foreign_keys=ON`.
2. **Mocked Faster-Whisper**:
   - `TranscriptionService` STT engine is mocked to return pre-computed clinical transcripts and word-level segments instantly without loading heavy neural network weights into memory.
3. **Mocked Groq API Client**:
   - The Groq SDK client is mocked at the HTTP transport/client level, returning predictable structured JSON responses mimicking LLaMA 3.3.
4. **Mocked scispaCy & medspaCy**:
   - Fast tokenizers and lightweight rule matchers simulate biomedical NER and assertion tagging, bypassing the multi-gigabyte neural pipeline download during continuous testing.

---

## 5. What Is Explicitly NOT Tested in Automated CI

For transparency, the following external and environmental conditions are not exercised during automated `pytest` runs:

- **Real Audio Acoustic Processing**: STT tests do not perform acoustic decoding on multi-gigabyte raw audio files; synthetic audio headers and mock models are used instead.
- **Live Groq API Calls**: Tests do not send requests to the live Groq Cloud API to avoid consuming live tokens and depending on internet connectivity.
- **Clinical Accuracy of Diagnostic Predictions**: Tests verify structural validity, entity extraction, and assertion tagging, but do not provide clinical validation of medical diagnoses.
- **Production PostgreSQL Concurrent Transactions**: The automated test suite runs against SQLite; PostgreSQL is verified in staging environments via Docker Compose.
