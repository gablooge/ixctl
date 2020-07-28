from six.moves.urllib_parse import urlencode, unquote

from social_core.backends.oauth import BaseOAuth2
from social_core.exceptions import AuthFailed

from django.conf import settings


class TwentycOAuth2(BaseOAuth2):
    name = "twentyc"
    AUTHORIZATION_URL = settings.TWENTYC_OAUTH_AUTHORIZE_URL
    ACCESS_TOKEN_URL = settings.TWENTYC_OAUTH_ACCESS_TOKEN_URL
    PROFILE_URL = settings.TWENTYC_OAUTH_PROFILE_URL

    ACCESS_TOKEN_METHOD = "POST"

    DEFAULT_SCOPE = ["email", "profile", "api_keys", "provider:peeringdb"]
    EXTRA_DATA = ["peeringdb", "api_keys", "organizations"]

    def get_user_details(self, response):
        """Return user details."""
        if response.get("verified_user") != True:
            raise AuthFailed(self, "User is not verified")

        return {
            "username": response.get("given_name"),
            "email": response.get("email") or "",
            "first_name": response.get("given_name"),
            "last_name": response.get("family_name"),
        }

    def user_data(self, access_token, *args, **kwargs):
        """Load user data from service."""
        headers = {"Authorization": "Bearer %s" % access_token}
        data = self.get_json(self.PROFILE_URL, headers=headers)
        return data

    def request(self, url, method="GET", *args, **kwargs):
        if "/profile/" in url:
            kwargs.update(params={"referer": "fullctl"})
        return super().request(url, method=method, *args, **kwargs)
