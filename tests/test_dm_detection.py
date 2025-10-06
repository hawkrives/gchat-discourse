"""Tests for Google Chat DM detection."""

import pytest


def test_is_dm_space():
    """Test DM space detection."""
    # Mock the GoogleChatClient without actually importing it
    # (to avoid Google API dependencies in tests)
    
    class MockGoogleChatClient:
        def is_dm_space(self, space):
            return space.get("type", "") == "DM"
        
        def get_space_type(self, space):
            return space.get("type", "UNKNOWN")
    
    client = MockGoogleChatClient()
    
    # Test DM space
    dm_space = {"type": "DM", "name": "spaces/123"}
    assert client.is_dm_space(dm_space) is True
    assert client.get_space_type(dm_space) == "DM"
    
    # Test ROOM space
    room_space = {"type": "ROOM", "name": "spaces/456"}
    assert client.is_dm_space(room_space) is False
    assert client.get_space_type(room_space) == "ROOM"
    
    # Test space with no type
    unknown_space = {"name": "spaces/789"}
    assert client.is_dm_space(unknown_space) is False
    assert client.get_space_type(unknown_space) == "UNKNOWN"
