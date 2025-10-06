# Contributing to gchat-discourse

Thank you for your interest in contributing to the Google Chat ↔️ Discourse sync service!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/gchat-discourse.git`
3. Create a branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes
6. Commit: `git commit -m "Add your feature"`
7. Push: `git push origin feature/your-feature-name`
8. Open a Pull Request

## Development Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Install development dependencies (optional)
pip install pytest pytest-cov black flake8 mypy

# Run validation
python validate.py
```

## Code Style

- Follow PEP 8 style guidelines
- Use type hints where possible
- Add docstrings to all functions and classes
- Keep functions focused and single-purpose
- Use descriptive variable names

### Formatting

```bash
# Format code with black
black *.py

# Check with flake8
flake8 *.py --max-line-length=100
```

## Project Structure

```
gchat-discourse/
├── main.py                      # Main service entry point
├── config_loader.py             # Configuration management
├── db.py                        # Database operations
├── google_chat_client.py        # Google Chat API client
├── discourse_client.py          # Discourse API client
├── sync_gchat_to_discourse.py   # GChat → Discourse sync
├── sync_discourse_to_gchat.py   # Discourse → GChat sync
├── webhook_listener.py          # Flask webhook server
└── tests/                       # Test directory (to be added)
```

## Adding Features

### Adding a New API Method

1. Add the method to the appropriate client (`google_chat_client.py` or `discourse_client.py`)
2. Add error handling and logging
3. Update the sync modules if needed
4. Add documentation

### Adding a New Sync Feature

1. Identify which sync module to modify
2. Add the sync logic
3. Update the main service to call it
4. Test thoroughly to prevent loops
5. Document the feature

## Testing

Currently, the project doesn't have automated tests, but you should:

1. Test with a local Discourse instance
2. Test with a Google Chat space you control
3. Verify no infinite loops occur
4. Check logs for errors
5. Validate database state

Future contributions should include:
- Unit tests for individual functions
- Integration tests for sync flows
- Mock API responses for testing

## Pull Request Guidelines

- Provide a clear description of the changes
- Reference any related issues
- Ensure code passes validation (`python validate.py`)
- Update documentation if needed
- Keep commits focused and atomic
- Squash trivial commits

## Bug Reports

When reporting bugs, include:

- Python version
- Operating system
- Steps to reproduce
- Expected behavior
- Actual behavior
- Relevant log excerpts
- Configuration (sanitized, no credentials!)

## Feature Requests

When requesting features:

- Describe the use case
- Explain the expected behavior
- Suggest an implementation approach (optional)
- Consider backward compatibility

## Areas for Contribution

Here are some areas where contributions would be valuable:

### High Priority
- [ ] Automated tests (unit and integration)
- [ ] Attachment/file support
- [ ] Better formatting conversion between platforms
- [ ] Google Cloud Pub/Sub integration for real-time Google Chat events
- [ ] Error recovery and retry logic

### Medium Priority
- [ ] Message deletion handling
- [ ] User mention translation between platforms
- [ ] Reaction/emoji synchronization
- [ ] Multi-space batch operations
- [ ] Performance optimization for large spaces

### Low Priority
- [ ] Web UI for configuration
- [ ] Docker containerization
- [ ] Kubernetes deployment manifests
- [ ] Prometheus metrics
- [ ] Advanced filtering and routing rules

## Questions?

- Open an issue for questions
- Check existing issues and PRs
- Review the README documentation

## License

By contributing, you agree that your contributions will be licensed under the GPL-3.0 License.
