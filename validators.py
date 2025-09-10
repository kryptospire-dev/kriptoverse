# Optimized Validators Class - validators.py
import re
import logging
from typing import Optional, Tuple, List
from constants import (
    INVALID_BEP20_ADDRESSES,
    INVALID_USERNAMES,
    VALIDATION_LIMITS,
    VALID_IMAGE_EXTENSIONS,
    VALID_MIME_TYPES,
    REGEX_PATTERNS,
    USERNAME_INVALID_PATTERNS,
    TWITTER_INVALID_PATTERNS,
    INSTAGRAM_INVALID_PATTERNS,
    COINMARKETCAP_INVALID_PATTERNS,
    DANGEROUS_FILE_CHARS,
    DANGEROUS_SQL_WORDS,
    USER_ID_LIMITS,
    RATE_LIMITS,
    VALIDATION_SUMMARY,
    MIN_STEP,
    MAX_STEP
)

logger = logging.getLogger(__name__)

# Pre-compile regex patterns for performance optimization
COMPILED_PATTERNS = {
    'bep20_address': re.compile(r'^[a-fA-F0-9]{40}$'),
    'username': re.compile(r'^[a-zA-Z0-9._]+$'),
    'coinmarketcap_userid': re.compile(r'^[a-zA-Z0-9._-]+$'),
    'hexadecimal': re.compile(r'^[a-fA-F0-9]+$'),
    'url': re.compile(r'https?://[^\s]+'),
    'mention': re.compile(r'@\w+'),
    'hashtag': re.compile(r'#\w+'),
    'html_tags': re.compile(r'<[^>]*>'),
    'referral_code': re.compile(r'^REF[A-Z0-9]{8}$'),
    'spam_patterns': [
        re.compile(r'^\d+[a-z]+\d+$'),
        re.compile(r'^[a-z]+\d{4,}$'),
        re.compile(r'^\w+_bot$'),
        re.compile(r'^\w+official$')
    ]
}

class OptimizedValidators:
    """Optimized validation class with pre-compiled regex patterns"""

    @staticmethod
    def validate_bep20_address(address: str) -> Tuple[bool, str]:
        """Optimized BEP20 address validation"""
        if not address:
            return False, "Address cannot be empty"

        address = address.strip()
        if not address:
            return False, "Address cannot be empty after removing whitespace"

        if not address.startswith('0x'):
            return False, "BEP20 address must start with '0x'"

        if len(address) != VALIDATION_LIMITS['bep20_address_length']:
            return False, f"BEP20 address must be exactly {VALIDATION_LIMITS['bep20_address_length']} characters long"

        hex_part = address[2:]
        if not COMPILED_PATTERNS['bep20_address'].match(hex_part):
            return False, "BEP20 address can only contain hexadecimal characters"

        # Quick invalid address check
        address_lower = address.lower()
        if address_lower in [addr.lower() for addr in INVALID_BEP20_ADDRESSES]:
            return False, "Cannot use zero address, dead address, or other invalid addresses"

        # Quick pattern checks
        hex_lower = hex_part.lower()
        if hex_lower == '0' * 40 or len(set(hex_lower)) == 1:
            return False, "Invalid address pattern"

        return True, "Valid BEP20 address"

    @staticmethod
    def validate_username(username: str) -> Tuple[bool, str]:
        """Optimized username validation"""
        if not username:
            return False, "Username cannot be empty"

        username = username.lstrip('@').strip()
        if not username:
            return False, "Username cannot be empty after removing @ and spaces"

        # Length checks
        username_len = len(username)
        if username_len < VALIDATION_LIMITS['username_min_length']:
            return False, f"Username must be at least {VALIDATION_LIMITS['username_min_length']} characters long"
        if username_len > VALIDATION_LIMITS['username_max_length']:
            return False, f"Username cannot be longer than {VALIDATION_LIMITS['username_max_length']} characters"

        # Quick reserved username check
        if username.lower() in INVALID_USERNAMES:
            return False, f"Username '{username}' is reserved and cannot be used"

        # Optimized regex check
        if not COMPILED_PATTERNS['username'].match(username):
            return False, "Username can only contain letters, numbers, underscores (_), and dots (.)"

        # Quick boundary checks
        if not username[0].isalnum() or not username[-1].isalnum():
            return False, "Username must start and end with a letter or number"

        # Quick pattern checks
        if username.isdigit():
            return False, "Username cannot be all numbers"

        # Check for invalid patterns (optimized)
        for pattern in USERNAME_INVALID_PATTERNS:
            if pattern in username:
                return False, f"Username cannot contain '{pattern}'"

        # Platform-specific quick checks
        username_lower = username.lower()
        for pattern in TWITTER_INVALID_PATTERNS + INSTAGRAM_INVALID_PATTERNS:
            if pattern in username_lower:
                return False, f"Username cannot contain '{pattern}'"

        # Quick spam pattern check
        for compiled_pattern in COMPILED_PATTERNS['spam_patterns']:
            if compiled_pattern.match(username_lower):
                return False, "Username appears to follow a suspicious pattern"

        return True, "Valid username"

    @staticmethod
    def validate_coinmarketcap_userid(userid: str) -> Tuple[bool, str]:
        """Optimized CoinMarketCap User ID validation"""
        if not userid:
            return False, "CoinMarketCap User ID cannot be empty"

        userid = userid.strip()
        if not userid:
            return False, "CoinMarketCap User ID cannot be empty after removing spaces"

        # Length checks
        userid_len = len(userid)
        if userid_len < VALIDATION_LIMITS['coinmarketcap_userid_min_length']:
            return False, f"CoinMarketCap User ID must be at least {VALIDATION_LIMITS['coinmarketcap_userid_min_length']} characters long"
        if userid_len > VALIDATION_LIMITS['coinmarketcap_userid_max_length']:
            return False, f"CoinMarketCap User ID cannot be longer than {VALIDATION_LIMITS['coinmarketcap_userid_max_length']} characters"

        # Quick reserved check
        if userid.lower() in INVALID_USERNAMES:
            return False, f"User ID '{userid}' is reserved and cannot be used"

        # Optimized regex check
        if not COMPILED_PATTERNS['coinmarketcap_userid'].match(userid):
            return False, "CoinMarketCap User ID can only contain letters, numbers, underscores (_), dots (.), and hyphens (-)"

        # Quick boundary checks
        if not userid[0].isalnum() or not userid[-1].isalnum():
            return False, "CoinMarketCap User ID must start and end with a letter or number"

        # Quick validation checks
        if userid.isdigit():
            return False, "CoinMarketCap User ID cannot be all numbers"

        # Pattern checks (optimized)
        for pattern in USERNAME_INVALID_PATTERNS:
            if pattern in userid:
                return False, f"CoinMarketCap User ID cannot contain '{pattern}'"

        userid_lower = userid.lower()
        for pattern in COINMARKETCAP_INVALID_PATTERNS:
            if pattern in userid_lower:
                return False, f"CoinMarketCap User ID cannot contain '{pattern}'"

        return True, "Valid CoinMarketCap User ID"

    @staticmethod
    def validate_referral_code(referral_code: str) -> Tuple[bool, str]:
        """Optimized referral code validation"""
        if not referral_code:
            return False, "Referral code cannot be empty"

        referral_code = referral_code.strip()
        if not referral_code:
            return False, "Referral code cannot be empty after removing spaces"

        # Length checks
        code_len = len(referral_code)
        if code_len < VALIDATION_LIMITS['referral_code_min_length']:
            return False, f"Referral code must be at least {VALIDATION_LIMITS['referral_code_min_length']} characters long"
        if code_len > VALIDATION_LIMITS['referral_code_max_length']:
            return False, f"Referral code cannot be longer than {VALIDATION_LIMITS['referral_code_max_length']} characters"

        # Optimized format validation
        if not COMPILED_PATTERNS['referral_code'].match(referral_code):
            return False, "Referral code must start with 'REF' followed by alphanumeric characters"

        return True, "Valid referral code"

    @staticmethod
    def validate_screenshot(file_size: int, file_name: str, mime_type: Optional[str] = None) -> Tuple[bool, str]:
        """Optimized screenshot validation"""
        # File size limits
        if file_size > VALIDATION_LIMITS['file_max_size']:
            return False, f"File too large. Maximum size allowed: {VALIDATION_LIMITS['file_max_size'] // (1024*1024)}MB"
        if file_size < VALIDATION_LIMITS['file_min_size']:
            return False, "File too small. Minimum size: 1KB"

        if not file_name:
            return False, "File name cannot be empty"

        # Clean file name
        file_name = file_name.split('/')[-1].split('\\')[-1]

        # Quick extension check
        file_extension = None
        file_name_lower = file_name.lower()
        for ext in VALID_IMAGE_EXTENSIONS:
            if file_name_lower.endswith(ext):
                file_extension = ext
                break

        if not file_extension:
            return False, f"Invalid file type. Allowed types: {', '.join(VALID_IMAGE_EXTENSIONS)}"

        # MIME type validation
        if mime_type and mime_type not in VALID_MIME_TYPES:
            return False, f"Invalid MIME type: {mime_type}"

        # Security checks (optimized)
        for pattern in DANGEROUS_FILE_CHARS:
            if pattern in file_name:
                return False, f"File name contains invalid character: {pattern}"

        if len(file_name) > VALIDATION_LIMITS['filename_max_length']:
            return False, f"File name too long (max {VALIDATION_LIMITS['filename_max_length']} characters)"

        return True, "Valid screenshot"

    @staticmethod
    def validate_message_text(text: str, max_length: int = None) -> Tuple[bool, str]:
        """Optimized message text validation"""
        if max_length is None:
            max_length = VALIDATION_LIMITS['message_max_length']

        if not text:
            return False, "Message cannot be empty"

        # Quick length check
        if len(text) > max_length:
            return False, f"Message too long. Maximum {max_length} characters allowed"

        # Optimized spam detection
        cleaned_text = ' '.join(text.split())
        words = len(cleaned_text.split())
        
        if words == 0:
            return False, "Message cannot be empty"

        # Quick spam pattern count
        spam_count = 0
        spam_count += len(COMPILED_PATTERNS['url'].findall(text))
        spam_count += len(COMPILED_PATTERNS['mention'].findall(text))
        spam_count += len(COMPILED_PATTERNS['hashtag'].findall(text))

        if spam_count / words > RATE_LIMITS['spam_threshold']:
            return False, "Message appears to contain too much promotional content"

        return True, "Valid message"

    @staticmethod
    def validate_step_number(step: int) -> Tuple[bool, str]:
        """Optimized step number validation"""
        if not isinstance(step, int):
            return False, "Step must be a number"

        if step < MIN_STEP or step > MAX_STEP:
            return False, f"Step must be between {MIN_STEP} and {MAX_STEP}"

        return True, "Valid step number"

    @staticmethod
    def sanitize_input(text: str) -> str:
        """Optimized input sanitization"""
        if not text:
            return ""

        # Quick whitespace cleanup
        text = ' '.join(text.split())

        # Remove HTML tags (optimized)
        text = COMPILED_PATTERNS['html_tags'].sub('', text)

        # Remove SQL injection attempts (optimized)
        text_upper = text.upper()
        for sql_word in DANGEROUS_SQL_WORDS:
            text_upper = text_upper.replace(sql_word, '')
        
        return text.strip()

    @staticmethod
    def validate_user_id(user_id) -> Tuple[bool, str]:
        """Optimized user ID validation"""
        if not user_id:
            return False, "User ID cannot be empty"

        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            return False, "User ID must be a number"

        if user_id <= 0:
            return False, "User ID must be positive"

        if user_id < USER_ID_LIMITS['min_value'] or user_id > USER_ID_LIMITS['max_value']:
            return False, "User ID appears to be invalid"

        return True, "Valid user ID"

    @staticmethod
    def extract_referral_code_from_start_param(start_param: str) -> Optional[str]:
        """Optimized referral code extraction"""
        if not start_param:
            return None

        referral_code = start_param.strip()
        
        # Quick format check before full validation
        if referral_code.startswith('REF') and len(referral_code) >= VALIDATION_LIMITS['referral_code_min_length']:
            is_valid, _ = OptimizedValidators.validate_referral_code(referral_code)
            if is_valid:
                return referral_code

        return None

    @staticmethod
    def is_valid_referral_link_param(param: str) -> bool:
        """Quick referral parameter check"""
        if not param:
            return False
        return param.startswith('REF') and len(param) >= VALIDATION_LIMITS['referral_code_min_length']

    @classmethod
    def get_validation_summary(cls) -> dict:
        """Get validation rules summary"""
        return VALIDATION_SUMMARY

# For backward compatibility
Validators = OptimizedValidators
