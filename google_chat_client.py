"""
Google Chat API client module for interacting with Google Chat API.
"""

import logging
import os.path
from typing import Dict, List, Any, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# If modifying these scopes, delete the token.json file
SCOPES = ['https://www.googleapis.com/auth/chat.spaces.readonly',
          'https://www.googleapis.com/auth/chat.messages.readonly',
          'https://www.googleapis.com/auth/chat.messages']


class GoogleChatClient:
    """Client for interacting with Google Chat API."""

    def __init__(self, credentials_file: str, token_file: str):
        """
        Initialize the Google Chat API client.

        Args:
            credentials_file: Path to the OAuth 2.0 credentials JSON file
            token_file: Path to store/load the OAuth token
        """
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.creds = None
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate with Google Chat API using OAuth 2.0."""
        if os.path.exists(self.token_file):
            self.creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)

        # If there are no (valid) credentials available, let the user log in
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                    logger.info("Refreshed Google Chat API credentials")
                except Exception as e:
                    logger.error(f"Failed to refresh credentials: {e}")
                    self.creds = None

            if not self.creds:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES)
                self.creds = flow.run_local_server(port=0)
                logger.info("Obtained new Google Chat API credentials")

            # Save the credentials for the next run
            with open(self.token_file, 'w') as token:
                token.write(self.creds.to_json())

        self.service = build('chat', 'v1', credentials=self.creds)
        logger.info("Google Chat API client initialized")

    def get_space(self, space_id: str) -> Optional[Dict[str, Any]]:
        """
        Get details about a Google Chat space.

        Args:
            space_id: The space ID (e.g., 'spaces/AAAAAAAAAAA')

        Returns:
            Space details or None if error
        """
        try:
            space = self.service.spaces().get(name=space_id).execute()
            logger.debug(f"Retrieved space: {space_id}")
            return space
        except HttpError as error:
            logger.error(f"Error getting space {space_id}: {error}")
            return None

    def list_messages(self, space_id: str, page_size: int = 100, 
                     page_token: Optional[str] = None) -> Dict[str, Any]:
        """
        List messages in a space.

        Args:
            space_id: The space ID
            page_size: Number of messages to retrieve per page
            page_token: Token for pagination

        Returns:
            Dictionary with 'messages' list and optional 'nextPageToken'
        """
        try:
            request = self.service.spaces().messages().list(
                parent=space_id,
                pageSize=page_size,
                pageToken=page_token
            )
            response = request.execute()
            logger.debug(f"Listed {len(response.get('messages', []))} messages from {space_id}")
            return response
        except HttpError as error:
            logger.error(f"Error listing messages in {space_id}: {error}")
            return {'messages': []}

    def get_message(self, message_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific message.

        Args:
            message_name: The full message name (e.g., 'spaces/AAAAA/messages/BBBBB')

        Returns:
            Message details or None if error
        """
        try:
            message = self.service.spaces().messages().get(name=message_name).execute()
            logger.debug(f"Retrieved message: {message_name}")
            return message
        except HttpError as error:
            logger.error(f"Error getting message {message_name}: {error}")
            return None

    def create_message(self, space_id: str, text: str, 
                      thread_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Create a new message in a space or thread.

        Args:
            space_id: The space ID
            text: The message text
            thread_id: Optional thread ID to reply in a thread

        Returns:
            Created message details or None if error
        """
        try:
            message_body = {'text': text}
            
            if thread_id:
                message_body['thread'] = {'name': thread_id}

            message = self.service.spaces().messages().create(
                parent=space_id,
                body=message_body
            ).execute()
            logger.info(f"Created message in {space_id}")
            return message
        except HttpError as error:
            logger.error(f"Error creating message in {space_id}: {error}")
            return None

    def update_message(self, message_name: str, text: str) -> Optional[Dict[str, Any]]:
        """
        Update an existing message.

        Args:
            message_name: The full message name
            text: The new message text

        Returns:
            Updated message details or None if error
        """
        try:
            message = self.service.spaces().messages().update(
                name=message_name,
                updateMask='text',
                body={'text': text}
            ).execute()
            logger.info(f"Updated message: {message_name}")
            return message
        except HttpError as error:
            logger.error(f"Error updating message {message_name}: {error}")
            return None

    def list_spaces(self, page_size: int = 100) -> List[Dict[str, Any]]:
        """
        List all spaces the authenticated user is a member of.

        Args:
            page_size: Number of spaces to retrieve per page

        Returns:
            List of space details
        """
        try:
            spaces = []
            page_token = None
            
            while True:
                request = self.service.spaces().list(
                    pageSize=page_size,
                    pageToken=page_token
                )
                response = request.execute()
                
                spaces.extend(response.get('spaces', []))
                page_token = response.get('nextPageToken')
                
                if not page_token:
                    break
            
            logger.info(f"Listed {len(spaces)} spaces")
            return spaces
        except HttpError as error:
            logger.error(f"Error listing spaces: {error}")
            return []

    def is_dm_space(self, space: Dict[str, Any]) -> bool:
        """
        Check if a space is a direct message (DM) space.

        Args:
            space: Space object from Google Chat API

        Returns:
            True if the space is a DM, False otherwise
        """
        # Google Chat API uses 'type' field to indicate space type
        # DM spaces have type 'DIRECT_MESSAGE' or 'DM'
        space_type = space.get('type', space.get('spaceType', ''))
        return space_type in ['DIRECT_MESSAGE', 'DM']

    def get_space_members(self, space_id: str) -> List[Dict[str, Any]]:
        """
        Get all members of a space.

        Args:
            space_id: The space ID

        Returns:
            List of member details
        """
        try:
            members = []
            page_token = None
            
            while True:
                request = self.service.spaces().members().list(
                    parent=space_id,
                    pageSize=100,
                    pageToken=page_token
                )
                response = request.execute()
                
                members.extend(response.get('memberships', []))
                page_token = response.get('nextPageToken')
                
                if not page_token:
                    break
            
            logger.debug(f"Listed {len(members)} members in {space_id}")
            return members
        except HttpError as error:
            logger.error(f"Error listing members in {space_id}: {error}")
            return []

    def get_user_info(self, user_name: str) -> Optional[Dict[str, Any]]:
        """
        Get user information from Google Chat.

        Args:
            user_name: The user resource name (e.g., 'users/12345')

        Returns:
            User details or None if error
        """
        try:
            # Note: Google Chat API may have limited user info access
            # The user info is typically embedded in message sender data
            user = self.service.users().get(name=user_name).execute()
            logger.debug(f"Retrieved user info: {user_name}")
            return user
        except HttpError as error:
            logger.warning(f"Error getting user {user_name}: {error}")
            return None
