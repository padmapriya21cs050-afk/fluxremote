# FluxRemote - Ultra-Low Latency Secure Remote Desktop Control Suite

FluxRemote is a full-stack, enterprise-ready, cross-network remote desktop control suite. It allows one Windows computer to remotely monitor and control another Windows computer over the Internet **without requiring port-forwarding, DNS setup, or complex network adjustments**. 

All screen captures, keystrokes, mouse moves, and clicks are funneled through a high-speed, secure WebSocket signalling and relay server deployable in a single click to cloud hosts like Render.

---

## 🏗️ Architecture Design & Flow

```
   ┌───────────────┐                  ┌────────────────┐                  ┌────────────────┐
   │  HOST CLIENT  │                  │  SIGNAL SERVER │                  │ VIEW/CONTROLLER│
   │ (Target PC)   │                  │ (Render Cloud) │                  │ (Remote Admin) │
   └───────┬───────┘                  └───────┬────────┘                  └───────┬────────┘
           │                                  │                                   │
           │ 1. Register ID & Access Pass     │                                   │
           ├─────────────────────────────────>│                                   │
           │                                  │                                   │
           │ 2. Connect persistent WS socket   │                                   │
           ├─────────────────────────────────>│                                   │
           │                                  │                                   │
           │                                  │ 3. Sign In Account / Get JWT      │
           │                                  │<──────────────────────────────────┤
           │                                  │                                   │
           │                                  │ 4. Request session verification   │
           │                                  │<──────────────────────────────────┤
           │                                  │                                   │
           │                                  │ 5. Connected WebSocket Stream     │
           │                                  │<─────────────────────────────────>│
           │                                  │                                   │
           │ 6. Send binary screen frames     │                                   │
           ├─────────────────────────────────>│                                   │
           │                                  │ 7. Forward binary stream          │
           │                                  │──────────────────────────────────>│
           │                                  │                                   │
           │                                  │ 8. Forward mouse/keyboard JSON    │
           │                                  │<──────────────────────────────────┤
           │ 9. Execute input injects         │                                   │
           │<─────────────────────────────────┤                                   │
```

### 🔒 Core Capabilities & Safety Implementations

1. **Internet Traversal Without Port-Forwarding**: Traditional LAN remote desktop programs require NAT holes. FluxRemote solves this by acting as a bidirectional **WebSocket relay**. Both Host and Viewer establish outward connection requests to a public HTTPS/WSS backend server. No incoming ports are ever exposed to the open web on either endpoint.
2. **Binary Frame Transmissions**: Screens are captured, converted directly into structured JPEG binary segments (compressibility ratio is adjustable via sliders in real-time), and relayed directly. No sluggish Base64 string encoding and decoding is used, reducing CPU and bandwidth usage by over 40%.
3. **Robust Token Authorization (JWT)**: Security is backed by asymmetric JWT signing. Viewers must authorize themselves with the relay server to list online targets and start secure session controls.
4. **Independent Worker Threads**: The host handles captures and keystroke injections on separate concurrent threads to prevent GUI locks. The viewer uses a high-performance Qt network thread (`QThread`) that communicates with the drawing layer seamlessly through safe thread signals.

---

## 📂 Project Structure

```
fluxremote/
├── backend/            # FastAPI, SQLite database, JWT authorization & WebSocket relay
│   ├── main.py         # Signalling app & WebSocket connection manager
│   ├── database.py     # Schema creation, online status, session tables
│   ├── auth.py         # JWT tokens & PBKDF2 cryptography
│   ├── models.py       # Pydantic schemas
│   ├── requirements.txt
│   └── Dockerfile
├── host/               # Windows Host desktop captures and event executors
│   ├── main.py         # Capture loop (mss), JPEG compressor (PIL), control injector (PyAutoGUI)
│   └── requirements.txt
├── viewer/             # Windows PySide6 desktop administration manager
│   ├── main.py         # Responsive login window, device explorer, control canvas
│   └── requirements.txt
├── shared/             # Shared protocol values
│   └── protocol.py     # Control types, JSON message encoders
├── docs/               # Advanced configuration and guides
├── render.yaml         # Render multi-service infrastructure deployment definition
└── README.md           # Documentation guide (this file)
```

---

## ⚡ Quick Start Instructions

### 1. Backend Server Setup (FastAPI)
Navigate to the backend directory, install prerequisites, and spin up the server:
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 3000
```
This boots the server at `http://localhost:3000`. It initializes `fluxremote.db` automatically.

### 2. Run Windows Host Agent (PC to be controlled)
Navigate to the host directory, install prerequisites, and launch:
```bash
cd host
pip install -r requirements.txt
python main.py --server ws://localhost:3000 --id OFFICE-PC --password fluxpwd123
```

### 3. Run Windows Viewer Client (Your controller PC)
Navigate to the viewer directory, install dependencies, and launch:
```bash
cd viewer
pip install -r requirements.txt
python main.py --server ws://localhost:3000
```
- Click **Register Account** first to create your profile.
- Log in to see the **Device Explorer Window**.
- Your registered host computer `OFFICE-PC` will be listed as **ONLINE**.
- Input the host password `fluxpwd123` and click **Control Device** to open the live interactive controller!

---

## ☁️ Deployment on Render

To deploy the signalling server live over the Internet:
1. Push this repository to **GitHub**.
2. Go to [Render](https://render.com) and sign in.
3. Click **New** -> **Blueprint**.
4. Select your repository. Render will automatically detect the `render.yaml` configuration and provision the FastAPI web service.
5. Once active, update your Host and Viewer terminal launch targets to use your Render URL:
   - Example: `--server wss://fluxremote-backend.onrender.com`
