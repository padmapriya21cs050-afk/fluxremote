# FluxRemote - Remote Access Client

A modern, secure remote access client built with React and Vite that communicates with the FluxRemote Python backend.

## Features

- **Authentication**: Secure login with JWT token-based authentication
- **Device Management**: List and manage remote devices
- **Remote Viewing**: Real-time remote desktop streaming via WebSocket
- **Connection Status**: Live connection monitoring with latency tracking
- **Settings**: Configurable backend API URL
- **Responsive UI**: Modern dark-themed interface built with Tailwind CSS

## Prerequisites

- Node.js 16 or higher
- Python backend running (see [fluxremote/backend/README.md](fluxremote/backend/README.md))

## Installation

1. Install dependencies:
   ```bash
   npm install
   ```

2. Configure the backend API URL (optional):
   ```bash
   # Copy the example environment file
   cp .env.example .env.local
   
   # Edit .env.local and set VITE_API_URL to your backend
   # Default: https://fluxremote-mbyy.onrender.com
   ```

## Development

Start the development server:
```bash
npm run dev
```

The app will open at `http://localhost:5173`

## Building

Build for production:
```bash
npm run build
```

Preview the production build:
```bash
npm run preview
```

## Configuration

### Environment Variables

- `VITE_API_URL` - Backend API URL (default: `https://fluxremote-mbyy.onrender.com`)
- `GEMINI_API_KEY` - Gemini API key for the backend AI assistant. Set this in `fluxremote/backend/.env`, or in a root `.env` file if you want to keep all local config together.
- `GEMINI_API_URL` - Optional Gemini endpoint override. Defaults to `https://gemini.googleapis.com/v1/models/gemini-1.5-lite:generate`.

## Project Structure

```
src/
├── components/
│   └── RemoteClient.tsx    # Main application component
├── App.tsx                 # Root component
├── main.tsx                # Entry point
├── index.css               # Global styles
└── types.ts                # TypeScript type definitions
```

## Architecture

### Login Flow
1. User enters credentials
2. Frontend sends login request to `POST /api/auth/login`
3. Backend returns JWT token
4. Token stored in localStorage for subsequent requests

### Device Connection Flow
1. User selects a device
2. Frontend initiates connection via `POST /api/devices/{id}/connect`
3. Backend creates session and returns session ID
4. Frontend establishes WebSocket connection using session ID
5. Remote desktop frames streamed via WebSocket

### WebSocket Communication
The application uses WebSocket for real-time communication:
- **Backend URL**: `ws://backend-url/api/ws/{sessionId}`
- **Messages**: Frame data, cursor positions, clipboard updates
- **Encoding**: Binary frames for video/image data, JSON for control messages

## Troubleshooting

### "Connection refused" error
- Ensure the Python backend is running on the configured API URL
- Check `VITE_API_URL` environment variable
- Verify network connectivity between frontend and backend

### Login fails
- Verify correct username and password
- Ensure backend authentication service is running
- Check browser console for detailed error messages

### Remote view not displaying
- Verify WebSocket connection is established
- Check browser console for connection errors
- Ensure backend is sending frame data

## API Integration

### Expected Backend Endpoints

```
POST   /api/auth/login                    # User authentication
GET    /api/devices                       # List available devices
POST   /api/devices/{id}/connect          # Initiate connection
WS     /api/ws/{sessionId}                # Real-time streaming
```

### Response Formats

**Login Response:**
```json
{
  "token": "jwt-token-string",
  "expiresIn": 3600
}
```

**Devices List Response:**
```json
{
  "devices": [
    {
      "id": "device-id",
      "name": "Device Name",
      "status": "online|offline|in-session"
    }
  ]
}
```

**Connect Response:**
```json
{
  "sessionId": "session-id-for-websocket"
}
```

## Notes

- This is a frontend-only application
- All business logic and security is handled by the backend
- WebSocket connections require the backend to be running
- JWT tokens are stored in browser localStorage

## Contributing

Please refer to [fluxremote/backend/README.md](fluxremote/backend/README.md) for backend development information.

## License

See LICENSE file for details.

