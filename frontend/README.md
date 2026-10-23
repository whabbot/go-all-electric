# Go All-Electric frontend

React + Vite + TypeScript placeholder that calls the backend health endpoint through the Vite
dev proxy (`/api` -> `http://127.0.0.1:8000`). See the [root README](../README.md) for setup.

Never put API keys in `VITE_*` variables: Vite bundles those into the browser build. All keys
stay in the backend.
