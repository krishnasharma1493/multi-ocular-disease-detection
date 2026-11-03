"""Start the RetinaScreen web app (FastAPI backend + built React frontend) on one port.

    python src/demo.py                 # http://127.0.0.1:7860
    python src/demo.py --port 8000

Equivalent to `cd backend && uvicorn app.main:app --port 7860`. Needs a built frontend
(`cd frontend && npm run build`); backend/.env is optional (demo defaults apply without it).
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, 'backend')


def launch_demo(port=7860, host='127.0.0.1'):
    import uvicorn

    os.chdir(BACKEND)
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    uvicorn.run('app.main:app', host=host, port=port)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=7860)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    launch_demo(args.port, args.host)
