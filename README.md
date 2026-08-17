# Finly — Interactive AI Fish Exhibit

Finly is an interactive AI character for museums, exhibitions, aquariums,
educational spaces, and branded installations.

Visitors can interact with Finly through text or voice while the animated
character is streamed from Unreal Engine to a browser.

## Demo

Add your demo video link here.

## Features

- Real-time Unreal Engine Pixel Streaming character
- Browser-based visitor interface
- Text questions
- Microphone questions
- Speech transcription
- AI-generated responses
- Custom text-to-speech voice
- Visitor-question queue
- Local reverse-proxy deployment
- Multiple streamer support

## Architecture

```text
Visitor browser
      |
      v
Caddy reverse proxy
      |
      +--> Pixel Streaming player
      |
      +--> FastAPI visitor backend
                    |
                    +--> LLM
                    +--> Speech recognition
                    +--> Text-to-speech
                    +--> Unreal question bridge
```

## Technology

- Unreal Engine
- Pixel Streaming
- Python
- FastAPI
- JavaScript
- Groq API
- Whisper
- Chatterbox TTS
- Caddy
- WebSockets and WebRTC

## Project status

Working prototype demonstrated on a local network.

Production deployment would require authentication, monitoring,
content-management tools, security review, and client-specific configuration.

## Privacy and security

Do not commit API keys, certificates, private assets, or visitor recordings.

## Contact

Amin Widatalla 
aminmagdi21@gmail.com  
