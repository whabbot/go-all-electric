# Go All-Electric frontend

React + Vite + TypeScript demo UI that calls the backend through the Vite dev proxy
(`/api` -> `http://127.0.0.1:8000`), or runs on offline mocks with `VITE_USE_MOCKS=true`. See the [root README](../README.md) for setup.

Never put API keys in `VITE_*` variables: Vite bundles those into the browser build. All keys
stay in the backend.
