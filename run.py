"""Application launcher."""
import webbrowser
import threading
import uvicorn

PORT = 18088


def open_browser():
    import time
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")
