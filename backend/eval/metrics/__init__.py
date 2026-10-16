"""Metric implementations.

Offline (no API key, deterministic, CI-safe):
    asr        word error rate, medical-term error rate
    entities   precision / recall / F1, strict and lenient
    grounding  lexical hallucination and omission rates

Online (needs GROQ_API_KEY):
    judge      rubric scoring, claim-level entailment, human agreement
"""
