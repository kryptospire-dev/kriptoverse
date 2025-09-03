import re
import logging
import asyncio
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

class Validators:
    """Enhanced validation class with async support and performance optimizations"""

    @staticmethod
    def validate_bep20_address(address: str) -> Tuple[bool, str]:
        """Validate BEP20 (BSC) address with comprehensive checks - optimized version"""
        if not address:
            return False, "Address cannot be empty"

        # Remove whitespace and validate
        address = address.strip()
        if not address:
            return False, "Address cannot be empty after removing whitespace"

        # Quick format checks first (most efficient)
        if not address.startswith('0x'):
            return False, "BEP20 address must start with '0x'"

        if len(address) != VALIDATION_LIMITS['bep20_address_length']:
            return False, f"BEP20 address must be exactly {VALIDATION_LIMITS['bep20_address_length']} characters long (got {len(address)})"

        # Hexadecimal validation (optimized regex)
        hex_part = address[2:]  # Remove '0x' prefix
        if not re.match(REGEX_PATTERNS['bep20_address'], hex_part):
            return False, "BEP20 address can only contain hexadecimal characters (0-9, a-f, A-F)"

        # Check against known invalid addresses (case-insensitive)
        address_lower = address.lower()
        if address_lower in [addr.lower() for addr in INVALID_BEP20_ADDRESSES]:
            return False, "Cannot use zero address, dead address, or other invalid addresses"

        # Pattern checks (optimized)
        hex_lower = hex_part.lower()

        # Quick pattern validations
        if hex_lower == '0' * 40:
            return False, "Invalid address: cannot be all zeros"

        if len(set(hex_lower)) == 1:
            return False, "Invalid address: cannot be all the same character"

        logger.debug(f"Valid BEP20 address validated: {address[:10]}...{address[-6:]}")
        return True, "Valid BEP20 address"

    @staticmethod
    def validate_username(username: str) -> Tuple[bool, str]:
        """Validate social media username with enhanced performance"""
        if not username:
            return False, "Username cannot be empty"

        # Clean and validate
        username = username.lstrip('@').strip()
        if not username:
            return False, "Username cannot be empty after removing @ and spaces"

        # Length checks (most efficient first)
        username_len = len(username)
        if username_len < VALIDATION_LIMITS['username_min_length']:
            return False, f"Username must be at least {VALIDATION_LIMITS['username_min_length']} characters long"

        if username_len > VALIDATION_LIMITS['username_max_length']:
            return False, f"Username cannot be longer than {VALIDATION_LIMITS['username_max_length']} characters"

        # Reserved username check (optimized lookup)
        username_lower = username.lower()
        if username_lower in INVALID_USERNAMES:
            return False, f"Username '{username}' is reserved and cannot be used"

        # Character validation (single regex check)
        if not re.match(REGEX_PATTERNS['username'], username):
            return False, "Username can only contain letters, numbers, underscores (_), and dots (.)"

        # Start/end character validation
        if not username[0].isalnum() or not username[-1].isalnum():
            return False, "Username must start and end with a letter or number"

        # Pattern checks (optimized)
        for pattern in USERNAME_INVALID_PATTERNS:
            if pattern in username:
                return False, f"Username cannot contain '{pattern}'"

        # Additional validations
        if username.isdigit():
            return False, "Username cannot be all numbers"

        if len(set(username_lower)) < 2:
            return False, "Username appears to be invalid (too repetitive)"

        # Platform-specific checks (optimized)
        for pattern in TWITTER_INVALID_PATTERNS + INSTAGRAM_INVALID_PATTERNS:
            if pattern in username_lower:
                return False, f"Username cannot contain '{pattern}'"

        # Spam pattern checks (compiled regex for performance)
        for pattern in REGEX_PATTERNS['spam_patterns']:
            if re.match(pattern, username_lower):
                return False, "Username appears to follow a suspicious pattern"

        logger.debug(f"Valid username validated: @{username}")
        return True, "Valid username"

    @staticmethod
    def validate_coinmarketcap_userid(userid: str) -> Tuple[bool, str]:
        """Validate CoinMarketCap User ID with optimized performance"""
        if not userid:
            return False, "CoinMarketCap User ID cannot be empty"

        userid = userid.strip()
        if not userid:
            return False, "CoinMarketCap User ID cannot be empty after removing spaces"

        # Length validation
        userid_len = len(userid)
        if userid_len < VALIDATION_LIMITS['coinmarketcap_userid_min_length']:
            return False, f"CoinMarketCap User ID must be at least {VALIDATION_LIMITS['coinmarketcap_userid_min_length']} characters long"

        if userid_len > VALIDATION_LIMITS['coinmarketcap_userid_max_length']:
            return False, f"CoinMarketCap User ID cannot be longer than {VALIDATION_LIMITS['coinmarketcap_userid_max_length']} characters"

        # Reserved check
        userid_lower = userid.lower()
        if userid_lower in INVALID_USERNAMES:
            return False, f"User ID '{userid}' is reserved and cannot be used"

        # Character validation
        if not re.match(REGEX_PATTERNS['coinmarketcap_userid'], userid):
            return False, "CoinMarketCap User ID can only contain letters, numbers, underscores (_), dots (.), and hyphens (-)"

        # Start/end validation
        if not userid[0].isalnum() or not userid[-1].isalnum():
            return False, "CoinMarketCap User ID must start and end with a letter or number"

        # Pattern validations
        for pattern in USERNAME_INVALID_PATTERNS:
            if pattern in userid:
                return False, f"CoinMarketCap User ID cannot contain '{pattern}'"

        if userid.isdigit():
            return False, "CoinMarketCap User ID cannot be all numbers"

        if len(set(userid_lower)) < 2:
            return False, "CoinMarketCap User ID appears to be invalid (too repetitive)"

        # Platform-specific checks
        for pattern in COINMARKETCAP_INVALID_PATTERNS:
            if pattern in userid_lower:
                return False, f"CoinMarketCap User ID cannot contain '{pattern}'"

        # Spam pattern checks
        for pattern in REGEX_PATTERNS['spam_patterns']:
            if re.match(pattern, userid_lower):
                return False, "CoinMarketCap User ID appears to follow a suspicious pattern"

        logger.debug(f"Valid CoinMarketCap User ID validated: {userid}")
        return True, "Valid CoinMarketCap User ID"

    @staticmethod
    def validate_referral_code(referral_code: str) -> Tuple[bool, str]:
        """Validate referral code format with optimized performance"""
        if not referral_code:
            return False, "Referral code cannot be empty"

        referral_code = referral_code.strip()
        if not referral_code:
            return False, "Referral code cannot be empty after removing spaces"

        # Length validation
        code_len = len(referral_code)
        if code_len < VALIDATION_LIMITS['referral_code_min_length']:
            return False, f"Referral code must be at least {VALIDATION_LIMITS['referral_code_min_length']} characters long"

        if code_len > VALIDATION_LIMITS['referral_code_max_length']:
            return False, f"Referral code cannot be longer than {VALIDATION_LIMITS['referral_code_max_length']} characters"

        # Format validation (single regex check)
        if not re.match(REGEX_PATTERNS['referral_code'], referral_code):
            return False, "Referral code must start with 'REF' followed by alphanumeric characters (e.g., REFABC12345)"

        logger.debug(f"Valid referral code validated: {referral_code}")
        return True, "Valid referral code"

    @staticmethod
    def validate_screenshot(file_size: int, file_name: str, mime_type: Optional[str] = None) -> Tuple[bool, str]:
        """Validate screenshot file with optimized performance"""
        # File size limits (quick check first)
        if file_size > VALIDATION_LIMITS['file_max_size']:
            return False, f"File too large. Maximum size allowed: {VALIDATION_LIMITS['file_max_size'] // (1024*1024)}MB"

        if file_size < VALIDATION_LIMITS['file_min_size']:
            return False, "File too small. Minimum size: 1KB"

        # File name validation
        if not file_name:
            return False, "File name cannot be empty"

        # Remove path if present (optimized)
        file_name = file_name.split('/')[-1].split('\\')[-1]

        # Extension validation (optimized)
        file_name_lower = file_name.lower()
        file_extension = None
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

        # Length validation
        if len(file_name) > VALIDATION_LIMITS['filename_max_length']:
            return False, f"File name too long (max {VALIDATION_LIMITS['filename_max_length']} characters)"

        logger.debug(f"Valid screenshot validated: {file_name} ({file_size} bytes)")
        return True, "Valid screenshot"

    @staticmethod
    def validate_message_text(text: str, max_length: int = None) -> Tuple[bool, str]:
        """Validate message text with optimized spam detection"""
        if max_length is None:
            max_length = VALIDATION_LIMITS['message_max_length']

        if not text:
            return False, "Message cannot be empty"

        # Optimize whitespace handling
        cleaned_text = ' '.join(text.split())
        if len(cleaned_text) > max_length:
            return False, f"Message too long. Maximum {max_length} characters allowed"

        # Optimized spam detection
        words = cleaned_text.split()
        word_count = len(words)

        if word_count > 0:
            spam_count = 0
            # Count spam elements more efficiently
            for pattern_name in ['url', 'mention', 'hashtag']:
                spam_count += len(re.findall(REGEX_PATTERNS[pattern_name], text, re.IGNORECASE))

            # Check spam threshold
            if spam_count / word_count > RATE_LIMITS['spam_threshold']:
                return False, "Message appears to contain too much promotional content"

        return True, "Valid message"

    @staticmethod
    def validate_step_number(step: int) -> Tuple[bool, str]:
        """Validate step number with optimized checks"""
        if not isinstance(step, int):
            return False, "Step must be a number"

        if not (MIN_STEP <= step <= MAX_STEP):
            return False, f"Step must be between {MIN_STEP} and {MAX_STEP} (got {step})"

        return True, "Valid step number"

    @staticmethod
    def sanitize_input(text: str) -> str:
        """Sanitize user input with enhanced performance and security"""
        if not text:
            return ""

        # Optimize whitespace handling
        text = ' '.join(text.split())

        # Remove potential HTML/script tags (optimized regex)
        text = re.sub(REGEX_PATTERNS['html_tags'], '', text)

        # Remove potential SQL injection attempts (optimized)
        text_upper = text.upper()
        for sql_word in DANGEROUS_SQL_WORDS:
            # Case-insensitive replacement
            pattern = rf'\b{re.escape(sql_word)}\b'
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # Additional XSS protection
        dangerous_patterns = [
            r'javascript:', r'vbscript:', r'onload=', r'onerror=',
            r'onclick=', r'onmouseover=', r'<script', r'</script>'
        ]

        for pattern in dangerous_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        return text.strip()

    @staticmethod
    def validate_user_id(user_id) -> Tuple[bool, str]:
        """Validate Telegram user ID with optimized performance"""
        if not user_id:
            return False, "User ID cannot be empty"

        # Type conversion and validation
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            return False, "User ID must be a number"

        # Range validation (optimized)
        if user_id <= 0:
            return False, "User ID must be positive"

        if not (USER_ID_LIMITS['min_value'] <= user_id <= USER_ID_LIMITS['max_value']):
            return False, "User ID appears to be invalid or out of range"

        return True, "Valid user ID"

    @staticmethod
    def extract_referral_code_from_start_param(start_param: str) -> Optional[str]:
        """Extract and validate referral code with optimized performance"""
        if not start_param:
            return None

        referral_code = start_param.strip()
        is_valid, _ = Validators.validate_referral_code(referral_code)

        return referral_code if is_valid else None

    @staticmethod
    def is_valid_referral_link_param(param: str) -> bool:
        """Quick check if parameter could be a referral code - optimized"""
        if not param:
            return False

        return (param.startswith('REF') and
                len(param) >= VALIDATION_LIMITS['referral_code_min_length'] and
                len(param) <= VALIDATION_LIMITS['referral_code_max_length'])

    # Async validation methods for future API integrations
    async def validate_social_media_async(self, platform: str, username: str) -> Tuple[bool, str]:
        """Async validation for social media (placeholder for API integration)"""
        # For now, use sync validation
        if platform == 'twitter':
            return self.validate_username(username)
        elif platform == 'instagram':
            return self.validate_username(username)
        elif platform == 'coinmarketcap':
            return self.validate_coinmarketcap_userid(username)
        else:
            return False, f"Unsupported platform: {platform}"

    async def validate_bep20_address_async(self, address: str) -> Tuple[bool, str]:
        """Async BEP20 validation (placeholder for blockchain API integration)"""
        # For now, use sync validation
        # In future, this could check if address exists on blockchain
        return self.validate_bep20_address(address)

    @staticmethod
    def get_validation_summary() -> dict:
        """Get summary of all validation rules for documentation"""
        return VALIDATION_SUMMARY

    # Batch validation methods for performance
    @staticmethod
    def batch_validate_usernames(usernames: List[str]) -> List[Tuple[str, bool, str]]:
        """Batch validate multiple usernames for better performance"""
        results = []
        for username in usernames:
            is_valid, message = Validators.validate_username(username)
            results.append((username, is_valid, message))
        return results

    @staticmethod
    def batch_validate_addresses(addresses: List[str]) -> List[Tuple[str, bool, str]]:
        """Batch validate multiple BEP20 addresses for better performance"""
        results = []
        for address in addresses:
            is_valid, message = Validators.validate_bep20_address(address)
            results.append((address, is_valid, message))
        return results

    # Rate limiting validation
    @staticmethod
    def validate_rate_limit_key(key: str) -> bool:
        """Validate rate limiting key format"""
        if not key or len(key) > 100:
            return False
        return re.match(r'^[a-zA-Z0-9_:.-]+$', key) is not None

    # Enhanced security validations
    @staticmethod
    def is_suspicious_input(text: str) -> bool:
        """Check if input appears suspicious"""
        if not text:
            return False

        suspicious_patterns = [
            r'<script', r'javascript:', r'data:text/html',
            r'eval\(', r'exec\(', r'system\(', r'shell_exec',
            r'DROP\s+TABLE', r'DELETE\s+FROM', r'INSERT\s+INTO',
            r'UNION\s+SELECT', r'OR\s+1=1', r'AND\s+1=1'
        ]

        text_lower = text.lower()
        for pattern in suspicious_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True

        return False

    @staticmethod
    def clean_filename(filename: str) -> str:
        """Clean filename to prevent directory traversal and other attacks"""
        if not filename:
            return "unknown_file"

        # Remove path components
        filename = filename.split('/')[-1].split('\\')[-1]

        # Remove dangerous characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

        # Prevent hidden files and relative paths
        filename = filename.lstrip('.')

        # Limit length
        if len(filename) > 100:
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            filename = name[:95] + ('.' + ext if ext else '')

        return filename or "unknown_file"
