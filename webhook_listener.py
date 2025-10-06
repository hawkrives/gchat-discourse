"""
Webhook listener for receiving real-time updates from Discourse.
"""

import logging
from flask import Flask, request, jsonify
from typing import Callable, Dict, Any

logger = logging.getLogger(__name__)


class WebhookListener:
    """Flask-based webhook listener for Discourse events."""

    def __init__(self, host: str = '0.0.0.0', port: int = 5000):
        """
        Initialize the webhook listener.

        Args:
            host: Host to bind the server to
            port: Port to bind the server to
        """
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.post_handler = None
        self.topic_handler = None
        
        # Setup routes
        self._setup_routes()

    def _setup_routes(self):
        """Setup Flask routes for webhook handling."""
        
        @self.app.route('/discourse-webhook', methods=['POST'])
        def handle_webhook():
            """Handle incoming webhook from Discourse."""
            try:
                # Get the webhook payload
                payload = request.json
                
                if not payload:
                    logger.warning("Received empty webhook payload")
                    return jsonify({'status': 'error', 'message': 'Empty payload'}), 400

                # Log the event type
                event_type = request.headers.get('X-Discourse-Event-Type', 'unknown')
                event_name = request.headers.get('X-Discourse-Event', 'unknown')
                
                logger.info(f"Received webhook: {event_type}/{event_name}")
                logger.debug(f"Payload: {payload}")

                # Handle different event types
                if event_type == 'post':
                    self._handle_post_event(event_name, payload)
                elif event_type == 'topic':
                    self._handle_topic_event(event_name, payload)
                else:
                    logger.debug(f"Ignoring event type: {event_type}")

                return jsonify({'status': 'success'}), 200

            except Exception as e:
                logger.error(f"Error handling webhook: {e}", exc_info=True)
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/health', methods=['GET'])
        def health_check():
            """Health check endpoint."""
            return jsonify({'status': 'healthy'}), 200

    def _handle_post_event(self, event_name: str, payload: Dict[str, Any]):
        """Handle post-related events."""
        if not self.post_handler:
            logger.debug("No post handler registered")
            return

        post_data = payload.get('post', {})
        
        if event_name == 'post_created':
            logger.info(f"Post created: {post_data.get('id')}")
            self.post_handler('created', post_data)
        elif event_name == 'post_edited':
            logger.info(f"Post edited: {post_data.get('id')}")
            self.post_handler('edited', post_data)
        elif event_name == 'post_destroyed':
            logger.info(f"Post destroyed: {post_data.get('id')}")
            self.post_handler('destroyed', post_data)
        else:
            logger.debug(f"Ignoring post event: {event_name}")

    def _handle_topic_event(self, event_name: str, payload: Dict[str, Any]):
        """Handle topic-related events."""
        if not self.topic_handler:
            logger.debug("No topic handler registered")
            return

        topic_data = payload.get('topic', {})
        
        if event_name == 'topic_created':
            logger.info(f"Topic created: {topic_data.get('id')}")
            self.topic_handler('created', topic_data)
        elif event_name == 'topic_edited':
            logger.info(f"Topic edited: {topic_data.get('id')}")
            self.topic_handler('edited', topic_data)
        elif event_name == 'topic_destroyed':
            logger.info(f"Topic destroyed: {topic_data.get('id')}")
            self.topic_handler('destroyed', topic_data)
        else:
            logger.debug(f"Ignoring topic event: {event_name}")

    def register_post_handler(self, handler: Callable[[str, Dict[str, Any]], None]):
        """
        Register a handler for post events.

        Args:
            handler: Function that takes (event_name, post_data) as arguments
        """
        self.post_handler = handler
        logger.info("Post handler registered")

    def register_topic_handler(self, handler: Callable[[str, Dict[str, Any]], None]):
        """
        Register a handler for topic events.

        Args:
            handler: Function that takes (event_name, topic_data) as arguments
        """
        self.topic_handler = handler
        logger.info("Topic handler registered")

    def run(self):
        """Start the webhook listener server."""
        logger.info(f"Starting webhook listener on {self.host}:{self.port}")
        self.app.run(host=self.host, port=self.port, debug=False)
