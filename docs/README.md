# DiscordianAI Documentation

Welcome to the DiscordianAI documentation! This guide covers everything you need to know about setting up, configuring, and using the DiscordianAI bot.

## 📚 Documentation Index

### 🚀 Getting Started
- **[Setup Guide](Setup.md)** - Complete installation and setup instructions
- **[Configuration](Configuration.md)** - Complete configuration reference
- **[Python Versions](Python_Versions.md)** - Python version compatibility

### 🤖 AI Integration
- **[OpenAI-Compatible Integration](OpenAI.md)** - Ollama Cloud by default; OpenAI remains supported
- **[Perplexity Integration](Perplexity.md)** - Web search, citations, and Sonar models
- **[Smart Orchestration](HybridMode.md)** - How the bot chooses between AI services
- **[Routing Design](routing/DESIGN.md)** - Evidence model, gate rules, and invariants
- **[API Contract](API-CONTRACT.md)** - Request and response shapes for both providers
- **[Web Access](WebScraping.md)** – provider-side search and page fetch

### 💬 Message Handling
- **[Message Splitting](MessageSplitting.md)** - How long messages are handled
- **[Embed Limits](EmbedLimits.md)** - Discord embed size limits and strategies
- **[Image Attachments](Vision.md)** - Vision support, limits, and privacy
- **Conversational UX**
    - Bot shows typing indicators while AI responses are being generated
    - All replies are threaded (reply-to) and start with the requesting human's mention for clarity; bot authors are answered without a mention prefix

### 🔧 Infrastructure
- **[Architecture](Architecture.md)** - System design, patterns, and components
- **[Connection Pooling](ConnectionPooling.md)** - HTTP/2 connection optimization

### 🚀 Deployment
- **[Docker](Docker.md)** - Containerized deployment
- **[Daemon Mode](Daemon.md)** - Running as a background service

### 🛡️ Security & Development
- **[Security](Security.md)** - API key management, rate limiting, hardening
- **[API Parameter Validation](API_Validation.md)** - Startup checks for tokens, URLs, and keys
- **[Development Guide](Development.md)** - Modern workflow with black + ruff

### 📖 API Reference
- **[Sphinx API Docs](api/)** - Auto-generated API reference (build with `make -C docs html`)

---

## 🤖 AI Service Selection

The bot builds one evidence-based routing decision per message before calling a provider:

```mermaid
flowchart TD
    A["User Message"] --> GATE{"Bot addressed<br/>and channel allowed?"}
    GATE -->|"No"| Z["Ignore Message"]
    GATE -->|"Yes"| MODE{"Mode selector"}
    MODE -->|"Perplexity only"| PIMG{"Image attached?"}
    PIMG -->|"Yes"| PREF["Refuse image request<br/>(Perplexity cannot receive images)"]
    PIMG -->|"No"| F["Use Perplexity"]

    MODE -->|"OpenAI-compatible only"| J["Use chat provider"]
    MODE -->|"Hybrid"| IMG{"Image attached?"}
    IMG -->|"Yes"| ITERM["Chat answer with images<br/>(images:local; no reroute; empty answer is an error)"]
    IMG -->|"No"| S["Build RouterInput<br/>message + history"]

    S --> C{"Override: web instruction,<br/>URL, or local instruction?"}
    C -->|"web"| F
    C -->|"local"| J
    C -->|"No override"| G{"Any bearing cue?"}
    G -->|"Yes"| F
    G -->|"No"| H{"Short anaphoric<br/>follow-up?"}
    H -->|"Yes"| I["Inherit previous route"]
    I -->|"previous route web"| F
    I -->|"previous route local"| J
    H -->|"No"| J

    %% Only a hybrid, non-image local answer can reroute once to Perplexity
    J --> O["Chat Provider Response"]
    O --> WI{"Hybrid, non-image answer<br/>indicates web-inability?"}
    WI -->|"Yes, Perplexity not tried"| F
    WI -->|"No or already tried"| M["Local answer"]

    F --> L2["Web search + Citations"]
```

| Topic | Reference |
|-------------------|-----------|
| Set up the bot from scratch | [Setup Guide](Setup.md) |
| Configure bot settings | [Configuration](Configuration.md) |
| Set up the chat provider (Ollama Cloud by default) | [OpenAI-Compatible Integration](OpenAI.md) |
| Set up Perplexity API | [Perplexity Integration](Perplexity.md) |
| Understand the architecture | [Architecture](Architecture.md) |
| Deploy with Docker | [Docker](Docker.md) |
| Run as a service | [Daemon Mode](Daemon.md) |
| Contribute to development | [Development Guide](Development.md) |

---

## 🔗 External Resources

- **[GitHub Repository](https://github.com/johndotpub/DiscordianAI)**
- **[Issue Tracker](https://github.com/johndotpub/DiscordianAI/issues)**
- **[Discord.py Documentation](https://discordpy.readthedocs.io/)**
- **[OpenAI API Documentation](https://platform.openai.com/docs/)**
- **[Ollama Cloud](https://ollama.com/)**
- **[Perplexity API Documentation](https://docs.perplexity.ai/)**
