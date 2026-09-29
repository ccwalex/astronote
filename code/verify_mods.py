def main():
    for name in ("mcp", "fastapi", "httpx", "uvicorn", "multipart"):
        __import__(name)
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
