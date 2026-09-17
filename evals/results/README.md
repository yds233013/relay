# Investigator eval results

Live-model eval runs (`make eval-ai`) are written here with the provider, model id and prompt
version. They are manual, cost money, and never run in CI.

**No live run has been recorded.** No provider API key was available in the development
environment, so E1–E6 have been exercised only with the scripted provider (`make eval-ai-scripted`
and `backend/tests/integration/test_ai.py`), which tests the harness, tools and verifier, not a
model.
