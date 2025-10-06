"""
Configuration loader module for reading and validating config.yaml.
"""

import yaml
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class Config:
    """Configuration manager for the sync service."""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to the configuration file
        """
        self.config_path = config_path
        self.config = self._load_config()
        self._validate_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load the YAML configuration file."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
            return config
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML configuration: {e}")
            raise

    def _validate_config(self):
        """Validate that required configuration fields are present."""
        required_fields = {
            'discourse': ['url', 'api_key', 'api_username'],
            'google': ['credentials_file', 'token_file'],
            'sync_settings': ['poll_interval_minutes'],
            'mappings': []
        }

        for section, fields in required_fields.items():
            if section not in self.config:
                raise ValueError(f"Missing required configuration section: {section}")
            
            for field in fields:
                if field not in self.config[section]:
                    raise ValueError(f"Missing required field '{field}' in section '{section}'")

        if not self.config.get('mappings'):
            logger.warning("No space mappings defined in configuration")

        logger.info("Configuration validation passed")

    # Discourse configuration
    @property
    def discourse_url(self) -> str:
        """Get the Discourse URL."""
        return self.config['discourse']['url']

    @property
    def discourse_api_key(self) -> str:
        """Get the Discourse API key."""
        return self.config['discourse']['api_key']

    @property
    def discourse_username(self) -> str:
        """Get the Discourse username."""
        return self.config['discourse']['api_username']

    # Google configuration
    @property
    def google_credentials_file(self) -> str:
        """Get the Google credentials file path."""
        return self.config['google']['credentials_file']

    @property
    def google_token_file(self) -> str:
        """Get the Google token file path."""
        return self.config['google']['token_file']

    @property
    def pubsub_project_id(self) -> Optional[str]:
        """Get the Google Cloud Pub/Sub project ID."""
        return self.config['google'].get('pubsub', {}).get('project_id')

    @property
    def pubsub_subscription_id(self) -> Optional[str]:
        """Get the Google Cloud Pub/Sub subscription ID."""
        return self.config['google'].get('pubsub', {}).get('subscription_id')

    # Sync settings
    @property
    def poll_interval_minutes(self) -> int:
        """Get the polling interval in minutes."""
        return self.config['sync_settings']['poll_interval_minutes']

    @property
    def webhook_host(self) -> str:
        """Get the webhook listener host."""
        return self.config['sync_settings'].get('webhook_host', '0.0.0.0')

    @property
    def webhook_port(self) -> int:
        """Get the webhook listener port."""
        return self.config['sync_settings'].get('webhook_port', 5000)

    # Mappings
    @property
    def space_mappings(self) -> List[Dict[str, Any]]:
        """Get the list of space-to-category mappings."""
        return self.config.get('mappings', [])

    def get_mapping_for_space(self, space_id: str) -> Optional[Dict[str, Any]]:
        """Get the mapping configuration for a specific space."""
        for mapping in self.space_mappings:
            if mapping.get('google_space_id') == space_id:
                return mapping
        return None
