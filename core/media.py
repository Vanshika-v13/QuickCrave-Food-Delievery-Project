"""Image path normalization — no DB."""


def normalize_image_path(image_path):
    if not image_path or not str(image_path).strip():
        return None
    image_path = str(image_path)
    if image_path.startswith("http"):
        image_path = image_path.replace("http://localhost:8000", "")
        image_path = image_path.replace("http://127.0.0.1:8000", "")
    path = image_path.strip().lstrip("/")
    if path.startswith("images/"):
        return f"/{path}"
    return f"/images/{path}"
