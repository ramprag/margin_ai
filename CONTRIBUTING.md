# Contributing to Margin AI

First off, thank you for considering contributing to Margin AI! It's people like you that make Margin AI such a great cost-control platform for AI engineers.

## 1. Code of Conduct

By participating in this project, you are expected to uphold our Code of Conduct. Please treat all contributors with respect.

## 2. Issues and Bugs

If you find a bug, please file an issue using our **Bug Report Template**. Ensure you include:
- A clear descriptive title.
- Steps to reproduce the bug.
- The expected vs actual behavior.
- Screenshots if applicable.

## 3. Pull Request Process

We use a standard Git workflow:
1. Fork the repo and create your branch from `main`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation in `API.md` or `SDK.md`.
4. Ensure the test suite passes (`pytest tests/`).
5. Make sure your code adheres to standard PEP-8 style guidelines.
6. Issue that pull request using our **PR Template**!

## 4. Development Setup

To test Margin AI locally during development:

```bash
# Clone your fork
git clone https://github.com/ramprag/margin-ai.git
cd margin-ai

# Create virtual env
python -m venv venv
source venv/bin/activate # Windows: venv\Scripts\activate

# Install requirements
pip install -r backend/requirements.txt
pip install pytest

# Run the local gateway on port 8000
uvicorn backend.main:app --reload --port 8000
```

## 5. Adding New Providers
If you are adding a new model provider (e.g., Cohere, Mistral), please add the implementation to `backend/core/providers.py` extending the `LLMProvider` base class and update `backend/core/router.py` heuristics.
