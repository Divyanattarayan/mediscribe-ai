# MediScribe AI — Live Presentation & Demonstration Script

This script provides a structured, timed walkthrough for presenting MediScribe AI to evaluators, clinical juries, or technical stakeholders.

---

## Timing Overview
- **0:00 - 0:30 (30s)**: High-Impact Hook & Introduction
- **0:30 - 1:30 (60s)**: The Clinical Burden (Problem Statement)
- **1:30 - 3:30 (120s)**: Architectural Defense & Key Differentiators
- **3:30 - 6:00 (150s)**: Live End-to-End Product Demonstration
- **6:00 - 7:00 (60s)**: Limitations & Privacy Safeguards
- **7:00 - 10:00 (180s)**: Jury Q&A & Technical Defense

---

## 1. Introduction (0:00 - 0:30)

> "Good morning / afternoon everyone. My name is [Presenter Name], and today I am presenting **MediScribe AI** — an ambient clinical documentation system designed to turn real-time doctor-patient conversations into structured, verifiable, and clinician-approved SOAP notes.
> 
> Healthcare providers currently spend up to two hours typing notes for every one hour spent with a patient. MediScribe AI was built to solve clinical burnout without compromising medical accuracy or physician oversight."

---

## 2. The Problem Statement (0:30 - 1:30)

> "Clinicians face a documentation crisis:
> 1. **Administrative Burnout**: Physicians spend over 15 hours each week on 'pajama time' EHR documentation after clinic hours.
> 2. **Generic LLM Hallucinations**: Standard off-the-shelf generative AI models regularly hallucinate vitals, misinterpret patient negations (confusing 'denies chest pain' for 'patient has chest pain'), and invent findings.
> 3. **The Black Box Dilemma**: Doctors cannot trust an AI note unless they can trace exactly *why* a statement was made back to the raw conversation.
> 
> MediScribe AI directly addresses this with on-premise local speech recognition, biomedical entity extraction, assertion verification, and **verifiable statement-level evidence linking**."

---

## 3. System Architecture & Differentiators (1:30 - 3:30)

> *(Point to Architecture Diagram on Screen)*
> 
> "Our architecture separates the workflow into four verifiable stages:
> 
> 1. **On-Premise Audio Privacy**: Raw audio is ingested by an asynchronous FastAPI backend and transcribed locally using `faster-whisper`. Raw patient voice never leaves the host infrastructure.
> 2. **Clinical Gatekeeping**: Before invoking heavy language models, our `ContentValidator` evaluates clinical term density. Non-medical audio is rejected at the gate.
> 3. **Biomedical Entity & Assertion Extraction**: We use `scispaCy` trained on clinical corpora combined with `medspaCy`'s ConText algorithm. If a patient says *'My father had hypertension, but I deny headaches,'* our pipeline identifies that hypertension belongs to a family member, and headache is a negated symptom.
> 4. **Grounded SOAP Generation with Evidence Linking**: The note is drafted using LLaMA 3.3 via Groq with structured JSON outputs. Crucially, our `EvidenceLinkingService` runs fuzzy string alignment to link each generated statement back to exact transcript sentences. If a claim lacks supporting evidence, it is flagged as *'Evidence not found — review required'* rather than fabricated."

---

## 4. Live Product Demonstration (3:30 - 6:00)

### Step 1: Ingestion & Transcription (Dashboard to New Consultation)
> "Let's walk through a live clinical encounter.
> I navigate to **New Consultation**. I can either record live with my microphone or upload a consultation audio recording. Let's upload a standard clinical audio file.
> The file passes extension and MIME validation, and the local Whisper engine generates the transcript with word-level confidence scores."

### Step 2: Transcript Inspection & Correction
> "As a physician, I can review the transcript in the **Transcript Review** screen. If the speech recognizer misheard a medication brand name, I can edit the sentence directly. Notice that MediScribe AI allows me to correct the source record before medical entities are locked in."

### Step 3: Entity & Assertion Extraction
> "Clicking **Extract Medical Information** triggers our biomedical NLP pipeline. You can see discrete tags appear: symptoms, medications, conditions, and procedures, along with assertion flags like *'Negated'* or *'Family History'*. This structured table feeds directly into note synthesis."

### Step 4: SOAP Draft & Interactive Evidence Highlighting
> "Next, we generate the SOAP note. In under two seconds, we have a complete four-part note: Subjective, Objective, Assessment, and Plan.
> 
> Notice two critical capabilities:
> - **Zero-Hallucination Vitals**: Because the clinician did not state blood pressure or pulse in the conversation, the Objective section does not invent them.
> - **Interactive Evidence Citations**: When I click on any statement in the Assessment or Plan, the interface immediately highlights the exact supporting transcript quote on the left. If no evidence was found, a warning banner alerts the reviewer."

### Step 5: Explicit Clinician Approval
> "Finally, the note remains in a draft review state until I, as the licensed clinician, review the text, make any final adjustments, and explicitly click **Approve Note**. The system records the approval timestamp, locks the consultation, and marks it ready for record archiving."

---

## 5. Limitations & Privacy Boundaries (6:00 - 7:00)

> "We believe in honest, safe AI engineering.
> - **Assistive, Not Diagnostic**: MediScribe AI is not a cleared medical device and does not diagnose disease or prescribe medications autonomously.
> - **Acoustic Bounds**: While English clinical dialogues perform exceptionally well, regional code-switching (such as mixed Tamil-English) requires further acoustic fine-tuning and mandatory clinician editing.
> - **Data Retention Control**: Audio files can be deleted with a single click immediately post-approval while preserving the text note."

---

## 6. Jury Q&A & Technical Defense Preparation (7:00 - 10:00)

### Question 1: "How do you prevent the LLM from hallucinating clinical facts?"
> **Answer**: "We employ a defense-in-depth approach:
> 1. The system prompt explicitly forbids the synthesis of undocumented vitals or findings.
> 2. The input to the LLM is constrained by the structured entity and assertion table produced by scispaCy and medspaCy.
> 3. After generation, our `EvidenceLinkingService` runs fuzzy string similarity against the transcript. Any claim without strong verbatim support is flagged with an explicit warning."

### Question 2: "Why use Groq instead of running an LLM completely locally?"
> **Answer**: "In a clinical clinic setting, physicians cannot wait 45 to 60 seconds for a local 70B parameter model to generate a note on consumer hardware. Groq provides ultra-low latency inference (~1-2 seconds) while keeping our computational footprint minimal. However, because our architecture is modular, the backend can easily be pointed to an on-premise vLLM or Ollama instance if zero cloud data egress is strictly mandated."

### Question 3: "What happens if the clinician disagrees with an extracted assertion?"
> **Answer**: "MediScribe AI enforces human-in-the-loop oversight at every step. Clinicians can edit the transcript prior to extraction, edit the entities themselves, and directly modify the text of any SOAP section before providing their final approval."
