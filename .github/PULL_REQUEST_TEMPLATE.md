## Description
Please include a summary of the change and which provider/caching layer this impacts. List any dependencies that are required for this change.

Fixes # (issue)

## Type of change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New model provider (e.g., adding AWS Bedrock / Mistral via API)
- [ ] New feature (non-breaking change which adds functionality to the Margin AI gateway)
- [ ] Breaking change (fix or feature that would cause existing SDKs to not map to OpenAI spec correctly)

## Testing
Please describe the tests that you ran to verify your changes. Include curl commands verifying payload structure.
- [ ] Direct `/v1/chat/completions` API test (OpenAI SDK)
- [ ] Analytics tracking test (Verified dashboard logs correctly)
- [ ] PII redaction regression tested?

## Checklist:
- [ ] My code follows the PEP-8 style guidelines of this project
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas, like routing heuristics
- [ ] I have made corresponding changes to `API.md` and `SDK.md`
- [ ] I have verified no private API keys are checked in.
