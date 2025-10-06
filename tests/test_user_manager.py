"""Tests for user management module."""

import pytest
from gchat_discourse.user_manager import (
    sanitize_username,
    generate_email_from_gchat_user,
)


def test_sanitize_username_basic():
    """Test basic username sanitization."""
    assert sanitize_username("John Doe") == "john_doe"
    assert sanitize_username("alice-smith") == "alice_smith"
    assert sanitize_username("Bob_Jones") == "bob_jones"


def test_sanitize_username_special_chars():
    """Test removal of special characters."""
    assert sanitize_username("User@123!") == "user123"
    assert sanitize_username("Test#User$") == "testuser"
    assert sanitize_username("Name (With) Parens") == "name_with_parens"


def test_sanitize_username_length():
    """Test username length constraints."""
    # Long name should be truncated to 20 characters
    long_name = "This Is A Very Long Display Name"
    result = sanitize_username(long_name)
    assert len(result) <= 20
    
    # Short name should be padded
    assert len(sanitize_username("ab")) >= 3
    assert sanitize_username("ab") == "ab_user"


def test_sanitize_username_start_with_alphanumeric():
    """Test that username starts with alphanumeric."""
    assert sanitize_username("_username") == "username"
    assert sanitize_username("123user") == "123user"


def test_generate_email_from_gchat_user():
    """Test email generation from Google Chat user ID."""
    user_id = "users/123456789"
    email = generate_email_from_gchat_user(user_id)
    assert email == "gchat_123456789@gchat.local"
    
    # Test with custom domain
    email = generate_email_from_gchat_user(user_id, "example.com")
    assert email == "gchat_123456789@example.com"


def test_sanitize_username_unicode():
    """Test handling of unicode characters."""
    # Unicode should be removed or converted
    result = sanitize_username("José García")
    assert len(result) >= 3
    # Just verify it's a valid username format
    assert result.replace('_', '').replace('-', '').isalnum() or result == result.lower()
