# DiscordianAI Setup Guide

Complete setup guide for DiscordianAI with advanced AI orchestration and conversation consistency features.

## Prerequisites

- **Python 3.10 or higher** installed
- **Discord bot token** from Discord Developer Portal
- **At least one AI service API key** (OpenAI and/or Perplexity)

## Step 1: Discord Bot Creation

Create and configure your Discord bot:

1. **Create Application**
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   - Click "New Application" and give it a name
   - Navigate to the "Bot" section

2. **Configure Bot Settings**
   - Click "Add Bot" to create the bot user
   - **Copy the bot token** - you'll need this for configuration
   - Enable "Message Content Intent" under Privileged Gateway Intents (required for message processing)

3. **Set Bot Permissions**
   - Go to the "OAuth2" > "URL Generator" section
   - Select `bot` scope
   - Select required permissions:
     - Send Messages
     - Read Message History
     - Use Slash Commands (optional)
     - Embed Links
     - Attach Files (for file responses)

4. **Invite Bot to Server**
   - Copy the generated OAuth2 URL
   - Paste it in your browser and select your Discord server
   - Authorize the bot with the selected permissions

## Step 2: API Keys Setup

### Option A: Smart Hybrid Mode (Recommended) 🧠
Get both API keys for intelligent automatic service selection:

**OpenAI API Key** (for GPT-5):
- Go to [OpenAI Platform](https://platform.openai.com/api-keys)
- Create new API key
- Copy the key (starts with `sk-`)

**Perplexity API Key** (for web search):
- Go to [Perplexity Settings](https://www.perplexity.ai/settings/api)
- Generate API key
- Copy the key (starts with `pplx-`)

### Option B: Single Service Mode
Choose **either** OpenAI only **or** Perplexity only based on your needs.

## Step 3: Configuration

1. **Copy Configuration Template**
   ```bash
   cp config.ini.example config.ini
   ```

2. **Basic Configuration**
   Edit `config.ini` with your details:
   ```ini
   [Discord]
   DISCORD_TOKEN=your_discord_bot_token_here
   ALLOWED_CHANNELS=general,bot-testing
   
   [Default] 
   # For Smart Hybrid Mode, provide both:
   OPENAI_API_KEY=your_openai_api_key_here
   PERPLEXITY_API_KEY=your_perplexity_api_key_here
   
   # For single service, leave one empty:
   # OPENAI_API_KEY=your_openai_key  # OpenAI only
   # PERPLEXITY_API_KEY=      # Disable Perplexity
   ```

3. **Advanced Configuration (Optional)**
   Fine-tune the AI orchestration system:
   ```ini
   [Orchestrator]
   # How many recent messages to check for AI service consistency
   LOOKBACK_MESSAGES_FOR_CONSISTENCY=6
   
   # Minimum words before checking for entities in routing decisions  
   ENTITY_DETECTION_MIN_WORDS=10
   
   # Maximum conversation entries per user before pruning
   MAX_HISTORY_PER_USER=50
   
   # Memory cleanup interval in seconds (default: 1 hour)
   USER_LOCK_CLEANUP_INTERVAL=3600
   ```

## Step 4: Running the Bot

### Basic Usage
```bash
python -m src.main
```

### Advanced Usage
```bash
# Use specific config file
python -m src.main --conf production.ini

# Use config in specific folder
python -m src.main --folder /opt/discordianai --conf bot.ini
```

### Using the Control Script
The included `discordian.sh` script provides additional process management:
```bash
# Start the bot
./discordian.sh

# The script handles:
# - Process cleanup
# - Error checking  
# - Logging
# - Restart capabilities
```

## Step 5: Testing Your Setup

### Test Basic Functionality
Send these messages to your bot to verify it's working:

1. **General Response**: `Hello!` (should use GPT/conversational AI)
2. **Web Search**: `What's the latest AI news?` (should use Perplexity if available)
3. **Follow-up Consistency**: 
   - First: `What's the weather today?` (→ Perplexity)
   - Then: `Tell me more about that` (→ Should stay with Perplexity)

### Check Logs
Monitor `bot.log` for these messages:
```
INFO: Bot logged in successfully as YourBotName
INFO: Running in HYBRID mode (OpenAI + Perplexity) - Smart AI orchestration enabled
INFO: Smart orchestrator processing message from user...
INFO: Message analysis suggests web search would be beneficial - trying Perplexity first
```

## Production Deployment

### Security Best Practices
- **Never commit API keys** to version control
- **Use environment variables** in production:
  ```bash
  export DISCORD_TOKEN="your_token"
  export OPENAI_API_KEY="your_openai_key"
  export PERPLEXITY_API_KEY="your_perplexity_key"
  ```
- **Restrict config file permissions**: `chmod 600 config.ini`

### Performance Optimization
- **Monitor memory usage** - watch for cleanup log messages
- **Adjust conversation history** based on your server size
- **Use appropriate log level** for production (INFO or WARNING)
- **Consider Docker deployment** for isolation and scalability

### Monitoring & Maintenance
- **Log rotation**: Ensure log files don't grow too large
- **API usage tracking**: Monitor token consumption and costs
- **Error monitoring**: Set up alerts for critical errors
- **Regular updates**: Keep dependencies updated for security

## Troubleshooting

### Common Issues

**Bot doesn't respond**:
- Check `ALLOWED_CHANNELS` configuration
- Verify bot has "Send Messages" permission
- Ensure bot is mentioned in channel messages (DMs don't require mention)

**AI service not working**:
- Verify API keys are correct and active
- Check API usage limits/billing
- Review logs for specific error messages

**Memory issues**:
- Lower `MAX_HISTORY_PER_USER` value
- Decrease `USER_LOCK_CLEANUP_INTERVAL` for more frequent cleanup
- Monitor logs for cleanup messages

**Performance problems**:
- Increase `ENTITY_DETECTION_MIN_WORDS` to reduce processing
- Adjust `LOOKBACK_MESSAGES_FOR_CONSISTENCY` based on usage patterns

### Getting Help
- Check the logs first: `tail -f bot.log`
- Review configuration examples in `config.ini.example`
- Consult the [Configuration Guide](Configuration.md) for detailed parameter explanations
- See [HybridMode.md](HybridMode.md) for advanced AI orchestration features