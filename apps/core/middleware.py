class OrganizationMiddleware:
    """Attach the logged-in user's organization to every request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            request.organization = user.organization
        else:
            request.organization = None
        return self.get_response(request)
