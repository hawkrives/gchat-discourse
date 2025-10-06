#!/usr/bin/env python3
"""
Simple validation script to check if all modules can be imported.
This does not run the full service but validates the code structure.
Note: Dependencies must be installed for full validation.
"""

import sys
import ast
import os

def test_syntax():
    """Test that all Python files have valid syntax."""
    python_files = [
        'config_loader.py',
        'db.py',
        'google_chat_client.py',
        'discourse_client.py',
        'sync_gchat_to_discourse.py',
        'sync_discourse_to_gchat.py',
        'webhook_listener.py',
        'main.py'
    ]
    
    failed = []
    
    for filename in python_files:
        try:
            with open(filename, 'r') as f:
                ast.parse(f.read())
            print(f"✓ {filename} - syntax OK")
        except SyntaxError as e:
            print(f"✗ {filename}: {e}")
            failed.append(filename)
        except FileNotFoundError:
            print(f"✗ {filename}: File not found")
            failed.append(filename)
    
    if failed:
        print(f"\n{len(failed)} file(s) have syntax errors")
        return False
    else:
        print(f"\n✓ All {len(python_files)} Python files have valid syntax")
        return True

def test_imports():
    """Test that all modules can be imported (if dependencies are available)."""
    modules = [
        'config_loader',
        'db',
        'google_chat_client',
        'discourse_client',
        'sync_gchat_to_discourse',
        'sync_discourse_to_gchat',
        'webhook_listener',
        'main'
    ]
    
    success = []
    failed = []
    
    print("\nAttempting imports (requires dependencies to be installed):")
    for module_name in modules:
        try:
            __import__(module_name)
            print(f"✓ {module_name}")
            success.append(module_name)
        except ImportError as e:
            print(f"⚠ {module_name}: {e}")
            failed.append((module_name, str(e)))
    
    if success:
        print(f"\n✓ {len(success)} module(s) imported successfully")
    if failed:
        print(f"⚠ {len(failed)} module(s) require dependencies to be installed")
        print("  Run: pip install -r requirements.txt")
    
    return True  # Don't fail on missing dependencies

def check_config_template():
    """Check that config template exists."""
    if os.path.exists('config.yaml.example'):
        print("✓ config.yaml.example exists")
        return True
    else:
        print("✗ config.yaml.example not found")
        return False

def check_requirements():
    """Check that requirements.txt exists."""
    if os.path.exists('requirements.txt'):
        print("✓ requirements.txt exists")
        with open('requirements.txt', 'r') as f:
            lines = [l.strip() for l in f.readlines() if l.strip() and not l.startswith('#')]
            print(f"  Found {len(lines)} dependencies")
        return True
    else:
        print("✗ requirements.txt not found")
        return False

if __name__ == "__main__":
    print("Validating gchat-discourse implementation...\n")
    
    print("=" * 60)
    print("Checking files...")
    print("=" * 60)
    config_ok = check_config_template()
    req_ok = check_requirements()
    
    print("\n" + "=" * 60)
    print("Checking Python syntax...")
    print("=" * 60)
    syntax_ok = test_syntax()
    
    print("\n" + "=" * 60)
    print("Testing module imports...")
    print("=" * 60)
    imports_ok = test_imports()
    
    print("\n" + "=" * 60)
    if config_ok and req_ok and syntax_ok:
        print("✓ Validation PASSED")
        print("=" * 60)
        print("\nTo run the service:")
        print("1. Install dependencies: pip install -r requirements.txt")
        print("2. Configure: cp config.yaml.example config.yaml")
        print("3. Edit config.yaml with your credentials")
        print("4. Run: python main.py")
        sys.exit(0)
    else:
        print("✗ Validation FAILED")
        print("=" * 60)
        sys.exit(1)
