import re
import logging
from typing import Optional, Tuple, List
from utils.constants import (
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

class Validators:
    """Enhanced validation class for user inputs using constants with referral support"""

    @staticmethod
    def validate_bep20_address(address: str) -> Tuple[bool, str]:
        """
        Validate BEP20 (BSC) address with comprehensive checks
        Returns: (is_valid, error_message)
        """
        if not address:
            return False, "Address cannot be empty"

        # Remove whitespace and convert to lowercase for validation
        address = address.strip()
        if not address:
            return False, "Address cannot be empty after removing whitespace"

        # Basic format check: must start with 0x and be 42 characters long
        if not address.startswith('0x'):
            return False, "BEP20 address must start with '0x'"

        if len(address) != VALIDATION_LIMITS['bep20_address_length']:
            return False, f"BEP20 address must be exactly {VALIDATION_LIMITS['bep20_address_length']} characters long (got {len(address)})"

        # Check if contains only valid hexadecimal characters
        hex_part = address[2:]  # Remove '0x' prefix
        if not re.match(REGEX_PATTERNS['bep20_address'], hex_part):
            return False, "BEP20 address can only contain hexadecimal characters (0-9, a-f, A-F)"

        # Check against known invalid addresses
        if address.lower() in [addr.lower() for addr in INVALID_BEP20_ADDRESSES]:
            return False, "Cannot use zero address, dead address, or other invalid addresses"

        # Check for suspicious patterns
        hex_lower = hex_part.lower()
        # All zeros (beyond the standard zero address)
        if hex_lower == '0' * 40:
            return False, "Invalid address: cannot be all zeros"

        # All same character
        if len(set(hex_lower)) == 1:
            return False, "Invalid address: cannot be all the same character"

        # Simple pattern check (like 123456789... or abcdef...)
        if hex_lower == ''.join([hex(i)[-1] for i in range(40)]):
            return False, "Invalid address: appears to be a test pattern"

        logger.info(f"Valid BEP20 address validated: {address[:10]}...{address[-6:]}")
        return True, "Valid BEP20 address"

    @staticmethod
    def validate_username(username: str) -> Tuple[bool, str]:
        """
        Validate social media username (Twitter/Instagram) with enhanced checks
        Returns: (is_valid, error_message)
        """
        if not username:
            return False, "Username cannot be empty"

        # Remove @ if present and strip whitespace
        username = username.lstrip('@').strip()
        if not username:
            return False, "Username cannot be empty after removing @ and spaces"

        # Length checks
        if len(username) < VALIDATION_LIMITS['username_min_length']:
            return False, f"Username must be at least {VALIDATION_LIMITS['username_min_length']} characters long"

        if len(username) > VALIDATION_LIMITS['username_max_length']:
            return False, f"Username cannot be longer than {VALIDATION_LIMITS['username_max_length']} characters"

        # Check for reserved/invalid usernames
        if username.lower() in INVALID_USERNAMES:
            return False, f"Username '{username}' is reserved and cannot be used"

        # Character validation - allow letters, numbers, underscores, and dots
        if not re.match(REGEX_PATTERNS['username'], username):
            return False, "Username can only contain letters, numbers, underscores (_), and dots (.)"

        # Must start with letter or number
        if not username[0].isalnum():
            return False, "Username must start with a letter or number"

        # Must end with letter or number
        if not username[-1].isalnum():
            return False, "Username must end with a letter or number"

        # Cannot have consecutive special characters
        for pattern in USERNAME_INVALID_PATTERNS:
            if pattern in username:
                return False, f"Username cannot contain '{pattern}'"

        # Cannot be all numbers (most platforms don't allow this)
        if username.isdigit():
            return False, "Username cannot be all numbers"

        # Check for suspicious patterns
        if len(set(username.lower())) < 2:
            return False, "Username appears to be invalid (too repetitive)"

        # Platform-specific validations
        # Twitter-specific checks
        for pattern in TWITTER_INVALID_PATTERNS:
            if pattern in username.lower():
                return False, f"Username cannot contain '{pattern}'"

        # Instagram-specific checks
        for pattern in INSTAGRAM_INVALID_PATTERNS:
            if pattern in username.lower():
                return False, f"Username cannot contain '{pattern}'"

        # Check for common spam patterns
        for pattern in REGEX_PATTERNS['spam_patterns']:
            if re.match(pattern, username.lower()):
                return False, "Username appears to follow a suspicious pattern"

        logger.info(f"Valid username validated: @{username}")
        return True, "Valid username"

    @staticmethod
    def validate_coinmarketcap_userid(userid: str) -> Tuple[bool, str]:
        """
        Validate CoinMarketCap User ID with enhanced checks
        Returns: (is_valid, error_message)
        """
        if not userid:
            return False, "CoinMarketCap User ID cannot be empty"

        # Strip whitespace
        userid = userid.strip()
        if not userid:
            return False, "CoinMarketCap User ID cannot be empty after removing spaces"

        # Length checks
        if len(userid) < VALIDATION_LIMITS['coinmarketcap_userid_min_length']:
            return False, f"CoinMarketCap User ID must be at least {VALIDATION_LIMITS['coinmarketcap_userid_min_length']} characters long"

        if len(userid) > VALIDATION_LIMITS['coinmarketcap_userid_max_length']:
            return False, f"CoinMarketCap User ID cannot be longer than {VALIDATION_LIMITS['coinmarketcap_userid_max_length']} characters"

        # Check for reserved/invalid usernames
        if userid.lower() in INVALID_USERNAMES:
            return False, f"User ID '{userid}' is reserved and cannot be used"

        # Character validation - allow letters, numbers, underscores, dots, and hyphens
        if not re.match(REGEX_PATTERNS['coinmarketcap_userid'], userid):
            return False, "CoinMarketCap User ID can only contain letters, numbers, underscores (_), dots (.), and hyphens (-)"

        # Must start with letter or number
        if not userid[0].isalnum():
            return False, "CoinMarketCap User ID must start with a letter or number"

        # Must end with letter or number
        if not userid[-1].isalnum():
            return False, "CoinMarketCap User ID must end with a letter or number"

        # Cannot have consecutive special characters
        for pattern in USERNAME_INVALID_PATTERNS:
            if pattern in userid:
                return False, f"CoinMarketCap User ID cannot contain '{pattern}'"

        # Cannot be all numbers
        if userid.isdigit():
            return False, "CoinMarketCap User ID cannot be all numbers"

        # Check for suspicious patterns
        if len(set(userid.lower())) < 2:
            return False, "CoinMarketCap User ID appears to be invalid (too repetitive)"

        # CoinMarketCap-specific checks
        for pattern in COINMARKETCAP_INVALID_PATTERNS:
            if pattern in userid.lower():
                return False, f"CoinMarketCap User ID cannot contain '{pattern}'"

        # Check for common spam patterns
        for pattern in REGEX_PATTERNS['spam_patterns']:
            if re.match(pattern, userid.lower()):
                return False, "CoinMarketCap User ID appears to follow a suspicious pattern"

        logger.info(f"Valid CoinMarketCap User ID validated: {userid}")
        return True, "Valid CoinMarketCap User ID"

    @staticmethod
    def validate_referral_code(referral_code: str) -> Tuple[bool, str]:
        """
        Validate referral code format
        Returns: (is_valid, error_message)
        """
        if not referral_code:
            return False, "Referral code cannot be empty"

        # Strip whitespace
        referral_code = referral_code.strip()
        if not referral_code:
            return False, "Referral code cannot be empty after removing spaces"

        # Length checks
        if len(referral_code) < VALIDATION_LIMITS['referral_code_min_length']:
            return False, f"Referral code must be at least {VALIDATION_LIMITS['referral_code_min_length']} characters long"

        if len(referral_code) > VALIDATION_LIMITS['referral_code_max_length']:
            return False, f"Referral code cannot be longer than {VALIDATION_LIMITS['referral_code_max_length']} characters"

        # Format validation - must match REF + alphanumeric pattern
        if not re.match(REGEX_PATTERNS['referral_code'], referral_code):
            return False, "Referral code must start with 'REF' followed by alphanumeric characters (e.g., REFABC12345)"

        logger.info(f"Valid referral code validated: {referral_code}")
        return True, "Valid referral code"

    @staticmethod
    def validate_screenshot(file_size: int, file_name: str, mime_type: Optional[str] = None) -> Tuple[bool, str]:
        """
        Validate screenshot file with enhanced checks
        Returns: (is_valid, error_message)
        """
        # File size limits
        if file_size > VALIDATION_LIMITS['file_max_size']:
            return False, f"File too large. Maximum size allowed: {VALIDATION_LIMITS['file_max_size'] // (1024*1024)}MB"

        if file_size < VALIDATION_LIMITS['file_min_size']:
            return False, "File too small. Minimum size: 1KB"

        # File name validation
        if not file_name:
            return False, "File name cannot be empty"

        # Remove path if present
        file_name = file_name.split('/')[-1].split('\\')[-1]

        # Valid image extensions
        file_extension = None
        for ext in VALID_IMAGE_EXTENSIONS:
            if file_name.lower().endswith(ext):
                file_extension = ext
                break

        if not file_extension:
            return False, f"Invalid file type. Allowed types: {', '.join(VALID_IMAGE_EXTENSIONS)}"

        # MIME type validation (if provided)
        if mime_type and mime_type not in VALID_MIME_TYPES:
            return False, f"Invalid MIME type: {mime_type}"

        # File name security checks
        for pattern in DANGEROUS_FILE_CHARS:
            if pattern in file_name:
                return False, f"File name contains invalid character: {pattern}"

        # Check for reasonable file name length
        if len(file_name) > VALIDATION_LIMITS['filename_max_length']:
            return False, f"File name too long (max {VALIDATION_LIMITS['filename_max_length']} characters)"

        logger.info(f"Valid screenshot validated: {file_name} ({file_size} bytes)")
        return True, "Valid screenshot"

    @staticmethod
    def validate_message_text(text: str, max_length: int = None) -> Tuple[bool, str]:
        """
        Validate message text for length and content
        Returns: (is_valid, error_message)
        """
        if max_length is None:
            max_length = VALIDATION_LIMITS['message_max_length']

        if not text:
            return False, "Message cannot be empty"

        # Remove excessive whitespace
        cleaned_text = ' '.join(text.split())
        if len(cleaned_text) > max_length:
            return False, f"Message too long. Maximum {max_length} characters allowed"

        # Check for spam patterns
        spam_count = 0
        for pattern_name in ['url', 'mention', 'hashtag']:
            spam_count += len(re.findall(REGEX_PATTERNS[pattern_name], text, re.IGNORECASE))

        # If message is mostly spam elements, flag it
        words = len(cleaned_text.split())
        if words > 0 and spam_count / words > RATE_LIMITS['spam_threshold']:
            return False, "Message appears to contain too much promotional content"

        return True, "Valid message"

    @staticmethod
    def validate_step_number(step: int) -> Tuple[bool, str]:
        """
        Validate step number is within valid range
        Returns: (is_valid, error_message)
        """
        if not isinstance(step, int):
            return False, "Step must be a number"

        if step < MIN_STEP or step > MAX_STEP:
            return False, f"Step must be between {MIN_STEP} and {MAX_STEP} (got {step})"

        return True, "Valid step number"

    @staticmethod
    def sanitize_input(text: str) -> str:
        """
        Sanitize user input by removing potentially dangerous content
        Returns: sanitized text
        """
        if not text:
            return ""

        # Remove excessive whitespace
        text = ' '.join(text.split())

        # Remove potential HTML/script tags (basic)
        text = re.sub(REGEX_PATTERNS['html_tags'], '', text)

        # Remove potential SQL injection attempts (basic)
        for sql_word in DANGEROUS_SQL_WORDS:
            text = re.sub(rf'\b{sql_word}\b', '', text, flags=re.IGNORECASE)

        return text.strip()

    @staticmethod
    def validate_user_id(user_id) -> Tuple[bool, str]:
        """
        Validate Telegram user ID
        Returns: (is_valid, error_message)
        """
        if not user_id:
            return False, "User ID cannot be empty"

        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            return False, "User ID must be a number"

        # Telegram user IDs are positive integers
        if user_id <= 0:
            return False, "User ID must be positive"

        # Reasonable range check (Telegram user IDs are typically large)
        if user_id < USER_ID_LIMITS['min_value']:
            return False, "User ID appears to be invalid"

        if user_id > USER_ID_LIMITS['max_value']:
            return False, "User ID too large"

        return True, "Valid user ID"

    @staticmethod
    def extract_referral_code_from_start_param(start_param: str) -> Optional[str]:
        """
        Extract and validate referral code from /start command parameter
        Returns: referral_code if valid, None if invalid/missing
        """
        if not start_param:
            return None

        # Clean the parameter
        referral_code = start_param.strip()

        # Validate the referral code format
        is_valid, _ = Validators.validate_referral_code(referral_code)
        if is_valid:
            return referral_code

        return None

    @staticmethod
    def is_valid_referral_link_param(param: str) -> bool:
        """
        Check if parameter from /start command could be a referral code
        Returns: True if it looks like a referral code
        """
        if not param:
            return False

        # Basic check - should start with REF and be the right length
        return param.startswith('REF') and len(param) >= VALIDATION_LIMITS['referral_code_min_length']

    @classmethod
    def get_validation_summary(cls) -> dict:
        """
        Get summary of all validation rules for documentation
        Returns: dictionary with validation rules
        """
        return VALIDATION_SUMMARY
