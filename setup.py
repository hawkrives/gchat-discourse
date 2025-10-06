#!/usr/bin/env python3
"""
Quick setup script for gchat-discourse sync service.
This script helps users get started by setting up the configuration.
"""

import os
import sys
import shutil

def setup():
    """Run the setup process."""
    print("=" * 60)
    print("Google Chat ↔️ Discourse Sync Service Setup")
    print("=" * 60)
    print()
    
    # Check if config.yaml already exists
    if os.path.exists('config.yaml'):
        print("⚠ config.yaml already exists!")
        response = input("Do you want to overwrite it? (y/N): ").strip().lower()
        if response != 'y':
            print("Setup cancelled.")
            return False
    
    # Copy example config
    if not os.path.exists('config.yaml.example'):
        print("✗ config.yaml.example not found!")
        print("Please ensure you're running this from the project directory.")
        return False
    
    shutil.copy('config.yaml.example', 'config.yaml')
    print("✓ Created config.yaml from template")
    print()
    
    print("Next steps:")
    print("-" * 60)
    print()
    print("1. Set up Google Chat API:")
    print("   - Go to: https://console.cloud.google.com/")
    print("   - Create/select a project")
    print("   - Enable Google Chat API")
    print("   - Create OAuth 2.0 Client ID (Desktop app)")
    print("   - Download as 'credentials.json'")
    print()
    print("2. Set up Discourse API:")
    print("   - Go to your Discourse: /admin/api/keys")
    print("   - Create 'All-Access API Key'")
    print("   - Note your API key and username")
    print()
    print("3. Edit config.yaml:")
    print("   - Add your Discourse URL, API key, and username")
    print("   - Add space-to-category mappings")
    print()
    print("4. Set up Discourse webhook:")
    print("   - Go to: /admin/api/webhooks")
    print("   - Create webhook for 'http://YOUR_IP:5000/discourse-webhook'")
    print("   - Enable 'Post Event' and 'Topic Event'")
    print()
    print("5. Install dependencies:")
    print("   pip install -r requirements.txt")
    print()
    print("6. Run the service:")
    print("   python main.py")
    print()
    print("=" * 60)
    print("Setup complete! Edit config.yaml to continue.")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    try:
        if setup():
            sys.exit(0)
        else:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Setup failed: {e}")
        sys.exit(1)
