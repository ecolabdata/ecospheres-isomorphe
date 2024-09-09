from functools import wraps

from flask import abort, flash, session, url_for
from flask import redirect as flask_redirect


def authenticated(redirect: bool = True):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not all(k in session for k in ("url", "username", "password")):
                if redirect:
                    flash("Pas d'information de connexion trouvée en session", "error")
                    return flask_redirect(url_for("login_form"))
                else:
                    abort(401, "Pas d'information de connexion trouvée en session")
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def connection_infos() -> tuple[str, str, str]:
    return session["url"], session["username"], session["password"]
