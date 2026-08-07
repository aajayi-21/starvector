"""OpenRouter-backed providers for the image-understanding slots.

Spec: docs/specs/pool-curation.md section 8a. One HTTP client does all
POST traffic. Each slot provider sends one POST for each image, parses
and validates the response at the boundary, and caches it in the data
root with the image hash and the provider config_hash in the path
(R12).
"""
