# MiniMax H3 Benchmark

## Run suite + live UI

```bash
python benchmark_runner.py
```

Open http://127.0.0.1:8787/

## UI only / resume

```bash
python benchmark_runner.py --ui-only
python benchmark_runner.py --resume
```

## Options

| Flag | Default | Purpose |
|------|---------|---------|
| `--comfy-url` | `http://127.0.0.1:8188` | ComfyUI base URL |
| `--port` | `8787` | Results UI port |
| `--ui-only` | off | Serve existing results only |
| `--resume` | off | Skip cells already `done` |
| `--retry-failed` | off | With `--resume`, requeue failures |

Requires ComfyUI at http://127.0.0.1:8188 with the MiniMax H3 workflow models installed.
