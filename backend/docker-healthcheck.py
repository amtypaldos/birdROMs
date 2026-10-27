"""Container healthcheck: the app server is healthy if it answers HTTP at all.

Any HTTP status counts (a 400 just means 127.0.0.1 is not in DJANGO_ALLOWED_HOSTS); only a
refused or timed-out connection is unhealthy.
"""

import os
import sys
import urllib.error
import urllib.request

url = f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/api/auth/config/"
try:
    urllib.request.urlopen(url, timeout=4)
except urllib.error.HTTPError:
    pass
except OSError as exc:
    print(f"unhealthy: {exc}", file=sys.stderr)
    sys.exit(1)
