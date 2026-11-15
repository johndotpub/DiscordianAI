# Image Attachments (Vision)

DiscordianAI can answer questions about images posted in an allowed channel or
direct message. Send one or more images with a question, or send an image on its
own. The bot treats the image as the current turn and keeps the surrounding
conversation as text history.

## How to use it

- Post up to four images in the same message. A message with only images works;
  no caption is required.
- Accepted formats are PNG, JPEG, GIF, and WebP. The bot always checks the file
  signature and rejects bytes whose declared content type disagrees with the
  detected format.
- Each image may be at most 5 MiB. The size is checked from Discord's attachment
  metadata before download and again after the bytes arrive.
- Unsupported, oversized, unreadable, or extra attachments are skipped and
  logged by filename. The rest of the message is still answered.
- In a server channel, address the bot as usual (mention it); direct messages
  need no mention.

The default limits are controlled by `VISION_ENABLED`, `VISION_MAX_IMAGES`,
`VISION_MAX_BYTES`, and `VISION_TOKEN_ESTIMATE` in
[Configuration.md](Configuration.md). Setting `VISION_ENABLED=false` restores
the previous behavior and ignores attachments completely.

## Which provider sees the image

Images are sent to the OpenAI-compatible chat provider configured by
`OPENAI_API_URL` and `GPT_MODEL` (Ollama Cloud by default) as an OpenAI-style
`image_url` content part carrying a `data:` URL. The shipped default model,
`deepseek-v4.1-flash:1017`, accepts images on Ollama Cloud.

An image request is always routed to the chat provider. Perplexity never
receives image data, and an image request is not rerouted to Perplexity even if
the chat provider says it cannot reach the web. If only Perplexity is
configured, the bot returns a fixed notice instead of silently answering
without looking at the image.

The chat provider keeps its native web tools when `WEB_TOOLS` is enabled, so a
question about an image can still trigger a web lookup.

## Budget and history

Each image is charged a flat `VISION_TOKEN_ESTIMATE` (default 1000) prompt
tokens during budget trimming. The base64 payload is not counted as text and is
never truncated. When history has to be trimmed, whole older turns are dropped;
history itself stays text-only.

Conversation history records the user turn as a text label such as
`[image: photo.png] what is this?` or `[image]` when the filename is missing.
Image bytes and base64 are never written to history or logs. Logs record the
filename, the declared size, and the skip reason only.

## Privacy

Images are uploaded to the configured chat provider (Ollama Cloud by default)
as part of the model request. They are not written to disk by the bot, but they
leave the Discord process and are subject to that provider's retention policy.
Attachments from channels the bot is not allowed to answer in are never read.
