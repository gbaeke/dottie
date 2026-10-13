# Dottie desktop

A window onto a Dottie server, with a tray icon (asleep or awake), notifications and the last dottie reopened. It loads
the server's own web app, so sign-in and chat are the same as in the browser. How to install and remove it is in the
[main README](../README.md#desktop-app-linux).

- `src-tauri/src/lib.rs`: the window, the tray, and the two commands the page may call (`set_status`, `notify`).
- `src-tauri/src/bridge.js`: runs inside the page; remembers the last dottie and reports states and new messages.
- `src-tauri/capabilities/default.json`: the origins the page may call those commands from. Add your server here.

```bash
npm install
DOTTIE_URL=http://localhost:8370 npm run dev    # from source; the default URL is http://localhost:8370
```
