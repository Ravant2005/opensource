OCIS Dashboard — build instructions

This folder contains a minimal precompiled dashboard build pipeline using `esbuild`.

Quick start (from repository root):

1. Install node deps:

```bash
cd ocis/dashboard
npm install
```

2. Build once:

```bash
npm run build
```

3. Start the Python API (so `/ui/dist/main.js` is served):

```bash
cd ../..   # repository root
source .venv/bin/activate
python run.py
```

4. For iterative development use watch:

```bash
cd ocis/dashboard
npm run watch
```

Notes:
- `esbuild` is fast and requires no config for this simple bundle.
- After `npm run build` the app will be served at `/ui` and `index.html` loads `/ui/dist/main.js`.
