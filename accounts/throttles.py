from rest_framework.throttling import AnonRateThrottle


class AuthenticationThrottle(AnonRateThrottle):
    scope = "auth"

    def allow_request(self, request, view):
        # Always limit login/pairing, even when a caller sends an existing token.
        self.key = self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
        self.history = self.cache.get(self.key, [])
        self.now = self.timer()
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        return self.throttle_failure() if len(self.history) >= self.num_requests else self.throttle_success()
