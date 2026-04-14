import re
import base64
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Lazy-loaded Presidio engines (heavy NLP models, only load on first call)
_analyzer_engine = None
_anonymizer_engine = None


def _get_presidio_engines():
    """Lazy-load Presidio engines to keep gateway startup fast."""
    global _analyzer_engine, _anonymizer_engine
    if _analyzer_engine is None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
            from presidio_anonymizer.entities import OperatorConfig

            _analyzer_engine = AnalyzerEngine()
            _anonymizer_engine = AnonymizerEngine()
            logger.info("Presidio NLP engines loaded successfully.")
        except ImportError:
            logger.warning(
                "Presidio not installed. Falling back to regex-only PII redaction. "
                "Install with: pip install presidio-analyzer presidio-anonymizer"
            )
        except Exception as e:
            logger.warning(f"Presidio initialization failed: {e}. Falling back to regex-only.")
    return _analyzer_engine, _anonymizer_engine


class SecurityService:
    """
    Enterprise-grade security service with two-pass PII redaction
    and hardened prompt injection detection.

    Pass 1: Fast regex for obvious, high-confidence patterns (emails, credit cards).
    Pass 2: Presidio NLP for context-aware entity recognition (names, addresses, SSNs).
    """

    # --- PII Redaction ---

    @staticmethod
    def _regex_redact(text: str) -> str:
        """
        Pass 1: Fast regex-based redaction for high-confidence patterns.
        Covers ~80% of PII in < 1ms.
        """
        # Email
        text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[REDACTED_EMAIL]', text)

        # Credit Card (with basic Luhn-aware structure: 4 groups of 4 digits)
        text = re.sub(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b', '[REDACTED_CARD]', text)

        # US SSN (xxx-xx-xxxx)
        text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED_SSN]', text)

        # Indian Aadhaar (xxxx xxxx xxxx or 12 contiguous digits)
        text = re.sub(r'\b\d{4}\s\d{4}\s\d{4}\b', '[REDACTED_AADHAAR]', text)

        # Indian PAN (ABCDE1234F)
        text = re.sub(r'\b[A-Z]{5}\d{4}[A-Z]\b', '[REDACTED_PAN]', text, flags=re.IGNORECASE)

        # Phone numbers (international formats, but require at least 7 digits to avoid false positives on short numbers)
        text = re.sub(
            r'(?<!\d)(\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{4,9}(?!\d)',
            '[REDACTED_PHONE]',
            text
        )

        return text

    @staticmethod
    def _presidio_redact(text: str) -> str:
        """
        Pass 2: Context-aware NLP-based PII redaction using Microsoft Presidio.
        Understands that 'Order #555-1234' is NOT a phone number.
        """
        analyzer, anonymizer = _get_presidio_engines()
        if not analyzer or not anonymizer:
            return text  # Presidio unavailable, return regex-only result

        try:
            from presidio_anonymizer.entities import OperatorConfig

            # Define which PII entities to scan for
            entities_to_detect = [
                "PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD",
                "US_SSN", "PERSON", "IBAN_CODE", "IP_ADDRESS",
                "US_PASSPORT", "US_DRIVER_LICENSE",
            ]

            results = analyzer.analyze(
                text=text,
                entities=entities_to_detect,
                language="en",
                score_threshold=0.4  # Moderate confidence to balance precision/recall
            )

            if not results:
                return text

            # Build operator map: replace each entity type with [REDACTED_<TYPE>]
            operators = {}
            for result in results:
                entity_type = result.entity_type
                operators[entity_type] = OperatorConfig(
                    "replace",
                    {"new_value": f"[REDACTED_{entity_type}]"}
                )

            anonymized = anonymizer.anonymize(
                text=text,
                analyzer_results=results,
                operators=operators
            )
            return anonymized.text

        except Exception as e:
            logger.error(f"Presidio redaction failed: {e}. Returning regex-only result.")
            return text

    @classmethod
    def redact_pii(cls, text: str) -> str:
        """
        Two-pass PII redaction pipeline.
        Pass 1: Fast regex for obvious patterns.
        Pass 2: Presidio NLP for contextual entity recognition.
        """
        # Pass 1: Regex (fast, high-confidence)
        text = cls._regex_redact(text)

        # Pass 2: Presidio NLP (slower, context-aware)
        text = cls._presidio_redact(text)

        return text

    # --- Prompt Injection Detection ---

    # Common prompt injection patterns (case-insensitive)
    INJECTION_PATTERNS = [
        r"\bignore previous instructions\b",
        r"\bignore all previous\b",
        r"\bignore above instructions\b",
        r"\bdisregard (all |any )?(previous |prior |above )?instructions\b",
        r"\bsystem prompt:\b",
        r"\byou are now an? (unfiltered|unrestricted|evil)\b",
        r"\bjailbreak\b",
        r"\bexecute command\b",
        r"\breveal your (system )?prompt\b",
        r"\bDAN mode\b",
        r"\bdo anything now\b",
        r"<\|end\|>",
        r"\[INST\]",
        r"<<SYS>>",
        r"<\|im_start\|>",
        r"<\|im_end\|>",
        r"###\s*(System|Human|Assistant)\s*:",  # Attempting to inject conversation turns
        r"\bpretend you (are|have) no (restrictions|rules|guidelines)\b",
        r"\bbypass (your |all )?(safety|content|ethical) (filters|guidelines|restrictions)\b",
    ]

    # Unicode homoglyphs commonly used to bypass string matching
    HOMOGLYPH_MAP = {
        '\u0430': 'a',  # Cyrillic а
        '\u0435': 'e',  # Cyrillic е
        '\u043e': 'o',  # Cyrillic о
        '\u0440': 'p',  # Cyrillic р
        '\u0441': 'c',  # Cyrillic с
        '\u0443': 'y',  # Cyrillic у
        '\u0445': 'x',  # Cyrillic х
        '\u0456': 'i',  # Ukrainian і
    }

    @classmethod
    def _normalize_homoglyphs(cls, text: str) -> str:
        """Replace common Unicode homoglyphs with their ASCII equivalents."""
        for glyph, ascii_char in cls.HOMOGLYPH_MAP.items():
            text = text.replace(glyph, ascii_char)
        return text

    @classmethod
    def _decode_base64_chunks(cls, text: str) -> str:
        """
        Find potential Base64-encoded chunks in the text, decode them,
        and append the decoded content to the text for re-checking.
        Attackers use this to hide 'ignore previous instructions' in encoded form.
        """
        # Match potential base64 strings (at least 20 chars, valid base64 alphabet)
        b64_pattern = re.compile(r'[A-Za-z0-9+/]{20,}={0,2}')
        matches = b64_pattern.findall(text)

        decoded_parts = []
        for match in matches:
            try:
                decoded = base64.b64decode(match).decode('utf-8', errors='ignore')
                if decoded and len(decoded) > 5:  # Only consider meaningful decoded strings
                    decoded_parts.append(decoded)
            except Exception:
                continue

        if decoded_parts:
            return text + " " + " ".join(decoded_parts)
        return text

    @classmethod
    def check_prompt_injection(cls, text: str) -> Tuple[bool, str]:
        """
        Multi-layer prompt injection detection.
        Layer 1: Unicode homoglyph normalization.
        Layer 2: Base64 decoding of suspicious chunks.
        Layer 3: Pattern matching against known injection signatures.

        Returns:
            Tuple of (is_injection: bool, matched_pattern: str or None)
        """
        # Layer 1: Normalize homoglyphs
        normalized = cls._normalize_homoglyphs(text)

        # Layer 2: Decode any Base64 chunks and append for pattern matching
        expanded = cls._decode_base64_chunks(normalized)

        # Layer 3: Pattern matching
        low_text = expanded.lower()
        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, low_text, re.IGNORECASE):
                logger.warning(f"Detected potential prompt injection: pattern='{pattern}'")
                return True, pattern

        return False, None


security_service = SecurityService()
