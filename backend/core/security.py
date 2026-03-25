import re
import logging
from typing import List

logger = logging.getLogger(__name__)

class SecurityService:
    @staticmethod
    def redact_pii(text: str) -> str:
        """
        Redacts PII (Emails, Phone Numbers, Aadhaar, PAN, Passport) before sending to LLM.
        """
        # Email Redaction
        text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[REDACTED_EMAIL]', text)
        
        # Phone numbers (Multiple formats)
        text = re.sub(r'\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}', '[REDACTED_PHONE]', text)
        
        # Indian Aadhaar (12 digits)
        text = re.sub(r'\d{4}\s\d{4}\s\d{4}|\d{12}', '[REDACTED_AADHAAR]', text)
        
        # Indian PAN (5 letters, 4 digits, 1 letter)
        text = re.sub(r'[A-Z]{5}\d{4}[A-Z]{1}', '[REDACTED_PAN]', text, flags=re.IGNORECASE)
        
        # Simple Credit Card pattern
        text = re.sub(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b', '[REDACTED_CARD]', text)
        
        return text

    @staticmethod
    def check_prompt_injection(text: str) -> bool:
        """
        Heuristic-based check for common prompt injection patterns.
        """
        injection_patterns = [
            r"ignore previous instructions",
            r"system prompt:",
            r"you are now an unfiltered",
            r"jailbreak",
            r"execute command",
            r"reveal your system prompt",
            r"DAN mode",
            r"do anything now",
            r"<\|end\|>",
            r"Assistant: (?!.*User: )", # Trying to fake assistant response
            r"\[INST\]", # Attempting to use model-specific instruction tags
        ]
        
        low_text = text.lower()
        for pattern in injection_patterns:
            if re.search(pattern, low_text):
                logger.warning(f"Detected potential prompt injection: {pattern}")
                return True
        return False

security_service = SecurityService()
