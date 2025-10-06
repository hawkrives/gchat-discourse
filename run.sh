#!/bin/bash
# Helper script for common operations

set -e

case "$1" in
    install)
        echo "Installing dependencies..."
        pip install -r requirements.txt
        echo "✓ Dependencies installed"
        ;;
    setup)
        echo "Running setup..."
        python3 setup.py
        ;;
    validate)
        echo "Validating installation..."
        python3 validate.py
        ;;
    run)
        echo "Starting sync service..."
        python3 main.py
        ;;
    help|*)
        echo "gchat-discourse helper script"
        echo ""
        echo "Usage: ./run.sh [command]"
        echo ""
        echo "Commands:"
        echo "  install   - Install Python dependencies"
        echo "  setup     - Run interactive setup"
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
