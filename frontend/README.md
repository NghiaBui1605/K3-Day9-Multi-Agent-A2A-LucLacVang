# Olist Dispute Console

React + TypeScript + Tailwind v4 interface for the local Olist chatbot.

## Run locally

Start the Python chatbot API from the repository root:

```powershell
python src\chatbot.py
```

In a second terminal, start the frontend:

```powershell
cd frontend
npm.cmd run dev
```

Open the Vite address shown in the terminal, normally `http://localhost:5173`.
Set `VITE_API_BASE_URL` only when the API is not at `http://127.0.0.1:8000`.

## API contract

The client sends `POST /api/chat` with a natural-language `message` and prior
chat `history`. It uses `missing_fields` and `conversation_state` in the API
response to ask for a case ID or Olist order ID only when that data is needed.
The UI does not render raw agent reasoning; it presents only verified policy
results and evidence IDs.

## Production build

```powershell
npm.cmd run build
```
