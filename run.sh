#!/bin/bash
# Helper script for common operations

set -euo pipefail

case "${1:-help}" in
    install)
        echo "Installing dependencies..."
        uv sync
        echo "✓ Dependencies installed"
        ;;
    setup)
        echo "Running setup..."

        # Check if config.yaml already exists
        if [ -f "config.yaml" ]; then
            echo "⚠ config.yaml already exists!"
            read -r -p "Do you want to overwrite it? (y/N): " response
            # to-lower in a macOS-compatible way
            response="$(printf '%s' "$response" | tr '[:upper:]' '[:lower:]')"
            if [ "${response}" != "y" ]; then
                echo "Setup cancelled."
                exit 1
            fi
        fi

        # Ensure example exists
        if [ ! -f "config.yaml.example" ]; then
            echo "✗ config.yaml.example not found!"
            echo "Please ensure you're running this from the project directory."
            exit 1
        fi

        cp config.yaml.example config.yaml
        echo "✓ Created config.yaml from template"
        echo

        cat <<'EOF'
Next steps:
------------------------------------------------------------
1. Set up Google Chat API:
   - Go to: https://console.cloud.google.com/
   - Create/select a project
   - Enable Google Chat API
   - Create OAuth 2.0 Client ID (Desktop app)
   - Download as 'credentials.json'

2. Set up Discourse API:
   - Go to your Discourse: /admin/api/keys
   - Create 'All-Access API Key'
   - Note your API key and username

3. Edit config.yaml:
   - Add your Discourse URL, API key, and username
   - Add space-to-category mappings

4. Set up Discourse webhook:
   - Go to: /admin/api/webhooks
   - Create webhook for 'http://YOUR_IP:5000/discourse-webhook'
   - Enable 'Post Event' and 'Topic Event'

5. Install dependencies:
   pip install -r requirements.txt

6. Run the service:
   python main.py

------------------------------------------------------------
Setup complete! Edit config.yaml to continue.
EOF

        ;;
    run)
        echo "Starting sync service..."
        uv run gchat-discourse
        ;;
    help|*)
        echo "gchat-discourse helper script"
        echo ""
        echo "Usage: ./run.sh [command]"
        echo ""
        echo "Commands:"
        echo "  install   - Install Python dependencies"
        echo "  setup     - Run interactive setup (creates config.yaml)"
        echo "  validate  - Validate installation"
        echo "  run       - Start the sync service"
        echo "  help      - Show this help message"
        echo ""
        echo "First time setup:"
        echo "  1. ./run.sh setup"
        echo "  2. Edit config.yaml with your credentials"
        echo "  3. ./run.sh install"
        echo "  4. ./run.sh validate"
        echo "  5. ./run.sh run"
        ;;
esac
