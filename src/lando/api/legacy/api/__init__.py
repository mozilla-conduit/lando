def get():
    """Return a redirect repsonse to the swagger specification."""
    return None, 302, {"Location": "/swagger.json"}
