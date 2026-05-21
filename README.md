# Voice AI Clinic Backend

A scalable AI-powered backend server for handling real-time voice communication, WebSocket streaming, AI assistant responses, appointment management, and multilingual support for the Voice AI Clinic application.

---

# 🌐 Backend Overview

This backend handles:

* 🎤 Real-time voice streaming
* 🤖 AI assistant processing
* 🔊 Audio chunk handling
* 📡 WebSocket communication
* 📅 Appointment booking logic
* 🌍 Multi-language support
* 🧠 Session memory management
* ⚡ Low-latency communication
* 🔁 Automatic reconnect handling

---

# 🚀 Features

* Real-time WebSocket Server
* AI Voice Response System
* Appointment Booking APIs
* Session Tracking
* Multi-language Detection
* Audio Streaming
* Backend Latency Monitoring
* Live AI Response Generation
* Automatic Reconnection Support
* REST API + WebSocket Hybrid Architecture

---

# 🛠 Backend Tech Stack

## Core Technologies

* Node.js
* Express.js
* WebSocket
* TypeScript
* Render Deployment
* AI API Integration
* REST APIs

---

# 📁 Backend Project Structure

backend/
│
├── src/
│   ├── api/
│   ├── websocket/
│   ├── services/
│   ├── routes/
│   ├── controllers/
│   ├── middleware/
│   ├── utils/
│   ├── config/
│   ├── app.ts
│   └── server.ts
│
├── package.json
├── tsconfig.json
├── .env
├── README.md
└── render.yaml

---

# ⚙️ Installation

## 1️⃣ Clone Repository

git clone https://github.com/your-backend-repository.git

---

## 2️⃣ Move Into Backend Folder

cd backend

---

## 3️⃣ Install Dependencies

npm install

---

# ▶️ Run Development Server

npm run dev

Backend runs on:

http://localhost:3000

---

# 🏗 Production Build

npm run build

---

# 🚀 Start Production Server

npm start

---

# 🔐 Environment Variables

Create a file named:

.env

Example:

PORT=3000

OPENROUTER_API_KEY=your_api_key

WEBSOCKET_URL=wss://your-websocket-url.com

FRONTEND_URL=https://voice2727.netlify.app

NODE_ENV=production

---

# 📜 Important Scripts

## Development

"dev": "nodemon src/server.ts"

## Production Build

"build": "tsc"

## Production Start

"start": "node dist/server.js"

---

# 🌍 API Endpoints

## Health Check

GET /health

---

## Appointment API

POST /api/appointments

GET /api/appointments

---

## Session API

GET /api/session

POST /api/session

---

# 🔌 WebSocket Features

* Live audio chunk streaming
* Real-time AI responses
* User transcript streaming
* AI assistant audio responses
* Session synchronization
* Voice phase handling

---

# ☁️ Render Deployment Settings

## Build Command

npm install && npm run build

## Start Command

npm start

## Environment

Node

## Node Version

20.x

---

# 🔧 Render Environment Variables

Add in Render Dashboard:

PORT

OPENROUTER_API_KEY

FRONTEND_URL

NODE_ENV

WEBSOCKET_URL

---

# 🔒 CORS Configuration

Example:

app.use(cors({
origin: "https://voice2727.netlify.app",
credentials: true
}));

---

# 🌐 Frontend Connection Example

Frontend WebSocket Connection:

const socket = new WebSocket("wss://your-backend-url.com");

---

# 📡 Backend Deployment URL

Example:

https://your-backend.onrender.com

---

# 📤 GitHub Push Commands

git add .

git commit -m "backend deployment update"

git push origin main

---

# 🐞 Common Issues & Fixes

## WebSocket Connection Failed

Check:

* backend URL
* CORS settings
* HTTPS/WSS protocol
* Render deployment status

---

## CORS Error

Fix:

app.use(cors({
origin: "https://voice2727.netlify.app",
credentials: true
}));

---

## Render Build Failed

Run locally:

npm install

npm run build

---

## Environment Variable Missing

Check:

* Render Dashboard
* .env file
* variable spelling

---

# 🔐 Security Improvements

* Helmet.js
* Rate Limiting
* Environment Variable Protection
* HTTPS/WSS Encryption
* Secure API Key Storage

---

# 👨‍💻 Author

## Vishwa Jaganathan

* Final Year Mechatronics Engineering Student
* Full Stack Developer
* AI + Voice Application Developer

---

# 🔮 Future Improvements

* AI Symptom Detection
* Voice Authentication
* Prescription Generator
* Video Consultation
* Patient History Tracking
* Firebase Notifications
* AI Medical Suggestions

---

# 📜 License

This project is for educational and development purposes.
