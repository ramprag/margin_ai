# Security Policy

## Supported Versions

Margin AI promises long-term support for the following major versions:

| Version | Supported          | Security Patching End Date |
| ------- | ------------------ | -------------------------- |
| 1.x.x   | :white_check_mark: | Active                     |
| < 1.0   | :x:                | N/A                        |

## Reporting a Vulnerability

As Margin AI handles highly sensitive enterprise LLM traffic and API keys, we take security vulnerabilities extremely seriously.

*   **Do not open a public issue** for a vulnerability.
*   **Do not mention the vulnerability in a public PR**.

Instead, please send an email to `security@margin-ai.com` containing:
1. A description of the vulnerability and the impact.
2. Steps to securely patch or reproduce the issue.
3. Your expected timeline.

We will acknowledge your report within 24 hours and issue a zero-day patch as quickly as possible. We use CVE assignments when applicable.

## Penetration Testing and Auditing

Margin AI is built to run entirely stateless within your VPC. No payload data, PII, or API keys are ever transmitted back to Margin AI telemetry servers. We encourage internal DevOps teams to run full penetration tests on the control plane. 

If your SOC2/HIPAA auditors require a formal letter of attestation regarding PII DLP algorithms, please reach out to `enterprise@margin-ai.com`.
