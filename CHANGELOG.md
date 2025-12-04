# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.2.8.0] - 2025-12-04

### Added
- **🔐 Security Enhancements**: Comprehensive security improvements
  - Added dependency vulnerability scanning with `pip-audit` in CI/CD pipeline
  - Added GitHub Dependabot configuration for automated dependency updates
  - Added API key format validation (OpenAI keys must start with `sk-`, Perplexity with `pplx-`)
  - Validation provides clear error messages with links to key management pages
  - Added pre-commit hooks with `detect-secrets` to prevent committing API keys
  - Added black and ruff hooks for automated code quality checks
- **📖 Architecture Documentation**: Added comprehensive `docs/Architecture.md`
  - High-level system architecture with ASCII diagrams
  - Component overview and responsibilities
  - Request flow with Mermaid sequence diagrams
  - Design patterns documentation (circuit breaker, caching, DI, retry logic)
  - Security architecture, observability, and performance optimizations
  - Future considerations and scalability path
- **🔒 Security Documentation**: Added comprehensive `docs/Security.md`
  - API key management (environment variables, config files, Docker secrets)
  - Key format validation and rotation procedures
  - Pre-commit hooks configuration (detect-secrets)
  - Rate limiting documentation (per-user and API-level)
  - Input validation and sanitization
  - Network security (TLS, connection pooling, timeouts)
  - Docker security hardening recommendations
  - Incident response procedures and security checklist
- **📦 Package Improvements**: Modern Python packaging enhancements
  - Added `src/__init__.py` with proper package exports and metadata
  - Added `src/py.typed` marker file for PEP 561 type hints support
  - Enables type checkers (mypy, pyright) to use package type hints
  - Added module docstrings to `bot.py` and `config.py`
- **🧪 Test Coverage**: Comprehensive testing improvements
  - Added 15+ edge case tests for configuration loading (malformed files, invalid values, etc.)
  - Added comprehensive API validation tests (40+ test cases)
  - Added error recovery scenario tests (circuit breaker state transitions, retry logic)
  - Added message splitting edge case tests (unicode, emoji, mixed content)
  - Added load and stress tests for 10k+ concurrent users
  - Added dependency check tests (`test_dependency_check.py`) for startup validation
  - Tests cover invalid URLs, type coercion errors, API key format validation
  - Tests cover missing sections, empty files, special characters, unicode handling
  - Tests verify performance requirements and thread safety under high load
  - **Test coverage increased to 80.80%** (exceeds 80% minimum requirement)

### Fixed
- **⚙️ CI/CD Optimization**: Fixed workflow cache inefficiency
  - Removed redundant tox cache recreation and deletion steps
  - Eliminated conflicting cache operations
  - Reduced CI execution time by optimizing cache usage
  - Updated tox.ini to exclude build artifacts (`discordianai-*`) from linting
- **🔧 Code Quality**: Fixed 26 ruff lint errors across codebase
  - Used `contextlib.suppress()` for cleaner exception handling in graceful shutdown
  - Made exception handling more specific (replaced blind `Exception` catches)
  - Removed duplicate `cleanup_inactive_user_locks` method in conversation manager
  - Fixed unused variables and arguments across test files
  - Added `noqa` comments for intentional private member access in health monitoring
  - Fixed flaky timing test with generous tolerance for parallel execution
- **📄 Documentation**: Fixed model reference inconsistency
  - Updated README example to use `gpt-5-mini` instead of outdated `gpt-4o-mini`
  - Ensures documentation matches actual code defaults
- **🐛 Signal Handler**: Fixed graceful shutdown crash on SIGTERM
  - Signal handler was trying to create new event loop while one was running
  - Now raises KeyboardInterrupt which discord.py handles gracefully
  - Eliminates "Cannot run the event loop while another loop is running" error
- **🔑 API Key Validation**: Fixed overly strict API key format patterns
  - OpenAI keys can now be `sk-proj-xxx`, `sk-svcacct-xxx`, not just `sk-xxx`
  - Updated regex to allow hyphens and underscores in key body
  - Supports all modern OpenAI API key formats

### Changed
- **🐍 Python Compatibility**: Expanded Python version support
  - Changed `requires-python` from `==3.10.*` to `>=3.10` for broader compatibility
  - Supports Python 3.10, 3.11, 3.12 and future versions
  - Added Python 3.11/3.12 compatibility testing in CI (informational, non-blocking)
- **🚀 CI/CD Improvements**: Optimized GitHub Actions workflow
  - Upgraded to latest action versions (setup-python@v5, cache@v4, codecov@v4)
  - Added concurrency control to cancel stale runs and save CI minutes
  - Added job timeouts (15min tests, 5min lint/security) to prevent runaway jobs
  - Use built-in pip caching in setup-python for cleaner configuration
  - Added descriptive job names for better GitHub UI visibility
  - Simplified lint job to run black/ruff directly (faster than tox wrapper)
  - Fixed security scan to install dependencies before auditing
- **🧹 Configuration Consolidation**: Modern Python packaging cleanup
  - Removed redundant `pytest.ini` (config in `pyproject.toml [tool.pytest.ini_options]`)
  - Removed redundant `.flake8` (using ruff with config in `pyproject.toml [tool.ruff]`)
  - Consolidated all tool configuration into `pyproject.toml` (PEP 518, PEP 621)
- **♻️ Code Refactoring**: Eliminated duplicate constants
  - Consolidated `OPENAI_VALID_MODELS`, `PERPLEXITY_MODELS`, `DISCORD_ACTIVITY_TYPES` into `config.py`
  - Updated `api_validation.py` to import from `config.py` (single source of truth)
  - Added stricter URL validation patterns with end anchors
- **⬆️ Dependencies**: Upgraded all packages to latest bleeding edge versions
  - discord.py: 2.6.2 → 2.6.4
  - openai: 1.101.0 → 2.8.1 (major version upgrade with backward compatibility)
  - requests: 2.31.0 → 2.32.5
  - beautifulsoup4: 4.12.2 → 4.14.3
  - httpx: 0.28.0 → 0.28.1
  - black: → 25.11.0, ruff: → 0.14.7, pytest: → 9.0.1
  - pytest-asyncio: → 1.3.0, pytest-cov: → 7.0.0, pytest-xdist: → 3.8.0
  - coverage: → 7.12.0, tox: → 4.32.0, pip-audit: → 2.10.0
  - pre-commit: → 4.5.0, detect-secrets: → 1.5.0
- **⚙️ Infrastructure**: Improved Docker healthcheck
  - Enhanced healthcheck to validate bot configuration, not just Python import
  - Verifies config file can be loaded and validated
  - Provides better indication of bot readiness
- **🛡️ Reliability**: Enhanced reliability and monitoring
  - Added graceful shutdown handling with signal handlers (SIGTERM, SIGINT)
  - Added connection pool health monitoring and status checks
  - Added memory usage statistics to conversation manager
  - Graceful shutdown closes Discord connection, connection pools, and background tasks
- **📄 Documentation**: Enhanced documentation
  - Fixed 16 broken documentation links pointing to non-existent files
  - Fixed outdated GPT-4 model references (now GPT-5 series throughout)
  - Updated documentation index with Architecture and Security links
  - Added rate limiting and backoff strategy documentation to README

### Removed
- **🧹 Test Cleanup**: Removed duplicate test files
  - Removed `test_config_basic.py` (duplicates `test_config.py`)
  - Removed `test_bot_basic.py` (duplicates `test_openai_processing.py`)

## [v0.2.7.2] - 2025-01-23

### Fixed
- **Message Splitting Improvements**: Enhanced message splitting with recursion limit protection
  - Fixed HTTPException 400 Bad Request for messages exceeding Discord's 2000-character limit
  - Implemented proper recursion limit handling with graceful fallback
  - Added comprehensive message splitting test suite (26 test cases)
  - Ensured all message parts respect Discord's character limits
  - Preserved content integrity during splitting process
  - Added proper error handling and logging for recursion scenarios

### Added
- **Comprehensive Test Coverage**: New `tests/test_message_splitting.py` with 26 test cases
  - Basic message splitting functionality tests
  - Code block splitting tests
  - Integration tests for long messages
  - Edge case testing (empty messages, unicode, extreme lengths)
  - Recursion limit and truncation behavior tests
  - Content preservation verification

### Documentation
- **Enhanced Message Splitting Guide**: Updated `docs/MessageSplitting.md`
  - Added recursion limit protection section
  - Added troubleshooting for new features
  - Included Mermaid diagrams for recursion flow

## [v0.2.7.1] - 2025-09-23

### Fixed
- **HTTP/2 Dependency Issues**: Fixed production environment HTTP/2 fallback to HTTP/1.1
  - Updated `httpx[http2]>=0.28.0` and `h2>=4.3.0` in `requirements.txt`
  - Added HTTP/2 dependencies to `pyproject.toml` for consistency
  - Enhanced `docs/ConnectionPooling.md` with version requirements and troubleshooting guide
  - Resolved issue where httpx 0.25.1 had unreliable HTTP/2 support causing fallback

### Documentation
- **Connection Pooling Guide**: Added comprehensive troubleshooting section for HTTP/2 issues
- **Version Requirements**: Documented minimum versions for reliable HTTP/2 operation
- **Installation Commands**: Updated with specific version requirements

## [v0.2.7] - 2025-01-23

### Added
- **HTTP/2 Connection Pooling**: Optimized API client performance with configurable connection pools
  - `src/connection_pool.py` - Centralized connection pool management for OpenAI and Perplexity APIs
  - API-specific connection limits: OpenAI (50 max, 10 keepalive), Perplexity (30 max, 5 keepalive)
  - HTTP/2 support for improved throughput and multiplexed connections
  - Configurable via `config.ini` with `[ConnectionPool]` section
- **Enhanced Documentation**: Comprehensive connection pooling guide in `docs/ConnectionPooling.md`

### Changed
- **Conversation Management**: Streamlined conversation handling architecture
  - Removed redundant `src/conversations.py` module (functionality consolidated into `ThreadSafeConversationManager`)
  - Fixed conversation summary consistency across all operation modes (OpenAI-only, Perplexity-only, Hybrid)
  - Updated hybrid mode to use passed `conversation_summary` parameter consistently
- **Code Quality**: Improved codebase maintainability
  - Removed duplicate test files (`test_conversations.py`, `test_get_conversation_summary.py`)
  - Updated documentation to reflect current architecture
  - Enhanced test coverage for conversation management

### Fixed
- **Conversation Summary Consistency**: Fixed hybrid mode to use passed conversation summary parameter
- **Documentation Accuracy**: Updated CHANGELOG and documentation to reflect current file structure
- **Code Formatting**: Applied consistent black and ruff formatting across all files

### Performance
- **API Overhead Reduction**: Connection pooling reduces connection establishment overhead
- **Memory Efficiency**: Supports 10k+ users with <100MB conversation memory
- **Rate Limit Compliance**: Optimized connection pools respect API rate limits

## [v0.2.6] - 2025-01-25

### Fixed
- **🔗 Citation Hyperlinks**: Fixed Perplexity citations not rendering as clickable links in Discord
  - **Root Cause**: Discord only supports `[text](url)` hyperlinks in embeds, not regular messages
  - **API Discovery**: Perplexity API now provides citations in `citations` metadata field, not inline URLs
  - **Solution**: Implemented Discord embeds with citation metadata extraction for proper hyperlink formatting
  - **Result**: Citations now appear as clickable hyperlinks: `[[1]](https://source.com)`
- **📱 Message Splitting with Embeds**: Enhanced message splitting to properly handle Discord embeds
  - Embed with citations attached to first message part
  - Continuation messages sent as plain text
  - Preserves citation accessibility for long responses

### Added  
- **`CitationEmbedFormatter` Class**: New utility for creating Discord embeds with properly formatted citations
- **Enhanced Citation Processing**: Modern Perplexity API support with `citations` and `search_results` metadata extraction
- **Comprehensive Citation Tests**: 17 new tests covering end-to-end citation functionality
- **Debug Scripts**: Added `/scripts` folder with debugging utilities for citation testing
- **Smart Embed Decision Logic**: Automatically determines when to use embeds vs plain text

### Changed
- **Perplexity Response Format**: Now returns `(text, suppress_embeds, embed_data)` tuple
- **Citation Extraction**: Updated to use Perplexity API metadata fields instead of inline URL parsing
- **Message Sending Pipeline**: Updated to handle both text messages and embeds seamlessly  
- **Citation Display**: Citations only appear in embeds for Perplexity responses (OpenAI remains plain text)
- **Dependencies**: Updated to `discord.py>=2.6.2` and `openai>=1.101.0`

### Technical Details
- **Modern API Support**: Handles both `citations` array and `search_results` objects from Perplexity API
- **Discord Embed Limits**: Properly handles 4096 character description limit
- **Backward Compatibility**: Non-citation responses continue using plain text
- **Error Handling**: Graceful fallback to plain text if embed creation fails
- **Performance**: Maintains existing caching and deduplication optimizations

## [v0.2.5] - 2025-08-10

### Added
- **Extended Python Version Support**: Added official support for Python 3.10 only
- **GPT-5 Model Family**: Complete migration to GPT-5 variants (gpt-5, gpt-5-mini, gpt-5-nano, gpt-5-chat)
- **Smart AI Orchestration**: Intelligent routing between OpenAI and Perplexity based on query analysis
- **Thread-Safe Conversation Management**: Robust conversation history with metadata tracking
- **Comprehensive Error Handling**: Circuit breaker pattern, exponential backoff, and graceful degradation
- **Health Monitoring**: Real-time API health checks and performance metrics
- **Advanced Caching**: Response caching with TTL and request deduplication
- **Rate Limiting**: Per-user rate limiting with configurable thresholds
- **Message Processing**: Intelligent message splitting and Discord formatting
- **API Validation**: Startup parameter validation and configuration checks
- **Performance Monitoring**: Built-in performance tracking and optimization
- **Tox Multi-Version Testing**: Comprehensive testing with Python 3.10

### Changed
- **Linting Workflow**: Streamlined from 4 tools (isort + black + ruff + flake8) to 2 tools (black + ruff)
- **GPT Model Default**: Changed from gpt-4o-mini to gpt-5-mini for cost-effectiveness
- **Model Validation**: Updated to support new GPT-5 model family
- **CI/CD Pipeline**: Enhanced GitHub Actions with multi-version testing matrix
- **Configuration Management**: Centralized constants and improved validation
- **Error Recovery**: Enhanced retry logic and user-friendly error messages
- **Conversation Handling**: Improved context management and summarization
- **Documentation Structure**: Reorganized and expanded documentation with new guides and examples

### Technical Improvements
- **Type Annotation Compatibility**: Ensured all modern type hints work across supported Python versions
- **Dependency Compatibility**: Verified all dependencies work with supported Python versions
- **Testing Matrix**: Comprehensive testing across all supported Python versions
- **Code Quality**: Removed unused variables, cleaned up deprecated parameters
- **Performance**: Pre-compiled regex patterns and optimized data structures
- **Memory Management**: Efficient conversation pruning and cleanup
- **Async Operations**: Proper async/await patterns throughout codebase
- **Security**: Input sanitization and Discord markdown protection
- **Logging**: Structured logging with configurable levels and file output
- **Testing**: 25+ integration tests with comprehensive coverage

### Fixed
- **OpenAI API 400 Error**: Resolved by using supported GPT-5 model variants
- **Linting Conflicts**: Eliminated endless loop between isort and ruff
- **Test Failures**: Fixed all test failures related to GPT-5 model migration
- **Documentation**: Updated all model cards and configuration examples
- **CI Failures**: Resolved all GitHub Actions workflow issues
- **Code Comments**: Cleaned up leftover development comments and unused code
- **Parameter Validation**: Fixed API parameter validation for new models

## [v0.2.0] - 2025-07-16

### Added
- **Major Python Architecture Restructure** ([#180](https://github.com/johndotpub/DiscordianAI/pull/180)): Complete modularization from monolithic `bot.py` (+1,585 −531 lines)
- **Modular Package Structure**: Reorganized into standard Python package layout under `src/` directory:
  - `src/bot.py` - Main bot logic with modular dependencies and event handlers
  - `src/config.py` - Configuration management with hierarchical loading (CLI > env > defaults)
  - `src/conversation_manager.py` - Thread-safe conversation history management and summarization
  - `src/discord_bot.py` - Discord-specific utilities like activity status setting
  - `src/openai_processing.py` - OpenAI API interaction and message processing
  - `src/rate_limits.py` - Rate limiting functionality for user requests
  - `src/main.py` - Entry point with global exception handling and configuration loading
  - `src/__init__.py` - Package initialization
- **Enhanced CLI Support**: New `--folder` argument for base directory support with relative config/log resolution
- **Comprehensive Test Suite**: Full async testing capabilities with pytest-asyncio
  - Robust async tests for OpenAI processing including edge cases and error handling
  - Comprehensive test coverage for all modules (config, main, discord_bot, conversation_manager)
  - Modern testing patterns with dependency injection and realistic fake clients
- **Development Tooling**: Modernized development environment
  - Added `.flake8` and `pytest.ini` configuration files for consistency
  - PEP 621 compliant `pyproject.toml` with proper dev dependencies
  - Updated `tox.ini` for streamlined testing and environment management
  - Aligned black and ruff configurations (resolved E203, W503 conflicts)

### Changed
- **Complete Codebase Restructure**: Transformed from monolithic architecture to modular design
- **Configuration System**: Hierarchical configuration loading (CLI arguments > environment variables > defaults)
- **Error Handling**: Enhanced with global exception handler in main entry point for robust error logging
- **Code Quality**: Achieved full PEP8 compliance and reduced cyclomatic complexity
- **Testing Infrastructure**: Migrated to modern async testing patterns with comprehensive coverage
- **Documentation**: Updated and expanded documentation for new CLI, configuration hierarchy, and project structure
- **Packaging**: Modernized Python packaging standards with clean separation of runtime vs dev dependencies

### Fixed
- **Cyclomatic Complexity**: Refactored `run_bot` and message processing to reduce complexity and improve maintainability
- **Import Management**: Corrected all import paths and module references for new structure
- **Code Standards**: Fixed all flake8 errors (E203, E301, E302, E306, E501) and unused imports
- **Function Spacing**: Ensured proper blank lines before top-level functions for PEP8 compliance
- **Error Handling**: Improved robustness in message processing and OpenAI API calls with comprehensive try/catch blocks
- **Test Reliability**: Updated all tests for new modular layout ensuring 100% pass rate in CI
- **Daemon Compatibility**: Updated `discordian.sh` script to use modular entry point (`src/main.py`)

## [v0.1.9] - 2025-06-11

### Changed
- Upgraded OpenAI library to version 1.84.0
- Updated pytest to 8.4.0 for improved testing capabilities
- Enhanced dependency management with automated dependabot updates

### Added
- Combined pull request workflow for efficient dependency management
- Improved CI/CD pipeline with PR combination support

### Fixed
- Multiple dependency version bumps for security and compatibility
- Enhanced flake8 linting with version 7.2.0
- Updated pyflakes to 3.3.2 for better code analysis

## [v0.1.8] - 2025-02-26

### Added
- Discord-compatible formatting enhancements to system prompt
- Improved bot personality with better Discord integration

### Changed
- Enhanced system message configuration for more natural Discord interactions
- Updated OpenAI library through multiple version increments (1.61.x to 1.64.0)
- Improved websockets support with version 15.0 compatibility

### Fixed
- Better Discord message formatting and response handling
- Enhanced compatibility with Discord's markdown and formatting systems

## [v0.1.7] - 2024-04-19

### Added
- **Docker Support**: Complete containerization with Dockerfile and docker-compose
- GitHub Container Registry (GHCR) publishing workflow
- Enhanced Docker image optimization and performance improvements

### Changed
- **Breaking Change**: Python version support simplified to 3.10 only
- Improved Dockerfile compatibility across different environments
- Enhanced security by ensuring config.ini exclusion from Docker images
- Updated OpenAI library to version 1.17.1
- Modernized README.md with better documentation structure

### Fixed
- Docker workflow placement and configuration issues
- Enhanced container build process for better performance
- Improved dependency management in containerized environments

## [v0.1.6] - 2024-02-19

### Added
- **Docker Support**: Initial Docker implementation with Dockerfile
- Issue templates for better bug reporting and feature requests
- GitHub issue template structure for streamlined contributions
- Enhanced project documentation and contribution guidelines

### Changed
- Improved repository structure with better organization
- Updated dependency management with multiple library upgrades
- Enhanced testing framework with pytest 8.0.0 compatibility

### Fixed
- Resolved typing system changes and compatibility issues
- Fixed various dependency conflicts and version mismatches
- Improved error handling and stability

## [v0.1.5] - 2024-02-02

### Added
- **Message Splitting**: Automatic splitting of long responses to respect Discord's 2000-character limit
- Intelligent message splitting that preserves code blocks and formatting
- Enhanced logging system with better error tracking and debugging

### Fixed
- **Session Handling**: Major improvements to conversation session management
- Resolved issues with conversation history persistence
- Better handling of user session data across bot restarts

### Changed
- Improved response handling for better user experience
- Enhanced error recovery and graceful degradation
- Updated OpenAI library to version 1.10.0

## [v0.1.2] - 2024-01-07

### Added
- **Daemon Control Script**: `discordian.sh` bash script for production deployment
- Process management with automatic termination of existing instances
- Configurable daemon mode with background execution support
- Enhanced logging with timestamps and structured output
- **CI/CD Pipeline**: Complete GitHub Actions workflow setup
  - Automated testing with pytest
  - Code quality checks with flake8
  - Dependency security scanning
- **Dependency Management**: Automated dependency updates via dependabot
- Enhanced `.gitignore` for better development experience

### Changed
- Improved configuration handling and validation
- Enhanced error checking with pipeline failure detection
- Updated multiple dependencies for security and performance
- Better documentation with workflow badges

### Fixed
- Resolved flake8 compliance issues and code quality improvements
- Fixed Python package compatibility issues
- Enhanced stability and reliability of daemon operations

## [v0.1.1] - 2023-06-14

### Added
- **Unit Testing Framework**: Comprehensive test suite with pytest
- Code quality enforcement with flake8 linting
- Automated testing pipeline integration
- PEP8 compliance improvements across codebase

### Changed
- Reformatted entire codebase to align with PEP8 standards
- Enhanced code quality and maintainability
- Improved development workflow with testing automation

### Fixed
- Code style consistency issues
- Python formatting and structure improvements

## [v0.1.0] - 2023-06-06

### Added
- **Initial Release**: Complete Discord bot implementation
- OpenAI GPT API integration for intelligent responses
- Discord.py framework integration with modern async/await patterns
- Configuration management via INI files with environment variable support
- Rate limiting system to prevent spam and API abuse
- Conversation history tracking for context-aware responses
- Direct message and channel mention support
- Configurable bot presence and activity status
- Global exception handling for robust error management
- Shard support for scalability
- Comprehensive logging system
- Flexible deployment with command-line configuration options

### Features
- **Multi-Channel Support**: Configurable channel allowlist for targeted bot responses
- **Conversation Context**: Persistent conversation history per user for meaningful interactions
- **Rate Limiting**: Configurable rate limits to prevent abuse (default: 10 messages per 60 seconds)
- **Message Handling**: Support for both direct messages and channel mentions
- **Error Recovery**: Graceful error handling with detailed logging
- **Deployment Flexibility**: Support for custom configuration files and base folders
