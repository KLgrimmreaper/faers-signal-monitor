import time

import requests

BASE_URL = "https://api.fda.gov/drug/event.json"

# no rate limiter needed, backing off on a 429 is enough
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 3

# a key is needed for more than 100 per request, and skip is rejected above 25000
PAGE_SIZE = 100
PAGE_SIZE_WITH_KEY = 1000
MAX_SKIP = 25000


class OpenFdaError(Exception):
    pass


def build_search(drug, reaction):
    search = f'patient.drug.medicinalproduct:"{drug.upper()}"'
    if reaction:
        search += f' AND patient.reaction.reactionmeddrapt:"{reaction.upper()}"'
    return search


def get(url, params):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            if attempt == MAX_ATTEMPTS:
                raise OpenFdaError(f"could not reach openFDA: {exc}") from exc
            time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
            continue

        if response.status_code == 200:
            return response.json()
        # 404 is openfda saying nothing matched, not a failure
        if response.status_code == 404:
            return None
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_ATTEMPTS:
                raise OpenFdaError(
                    f"gave up after {attempt} attempts, last was HTTP {response.status_code}"
                )
            # 3, 6, 12. the rate limit resets per minute so a second or two is too soon
            time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
            continue
        raise OpenFdaError(f"HTTP {response.status_code} from openFDA: {response.text[:200]}")

    raise OpenFdaError("ran out of attempts")


def count_reports(search, api_key=None):
    params = {"search": search, "limit": 1}
    if api_key:
        params["api_key"] = api_key

    body = get(BASE_URL, params)
    if body is None:
        return 0
    return body["meta"]["results"]["total"]


def count_reports_in_range(since, until, api_key=None):
    return count_reports(f"receivedate:[{since} TO {until}]", api_key=api_key)


def fetch_reports(since, until, limit, api_key=None):
    # to+to form that openfda's own examples use comes back as http 500, needs spaces
    if limit <= 0:
        return []

    page_size = PAGE_SIZE_WITH_KEY if api_key else PAGE_SIZE
    page_size = min(page_size, limit)

    reports = []
    while len(reports) < limit:
        params = {
            "search": f"receivedate:[{since} TO {until}]",
            "limit": page_size,
            "skip": len(reports),
        }
        if api_key:
            params["api_key"] = api_key

        body = get(BASE_URL, params)
        if body is None:
            break

        page = body.get("results", [])
        if not page:
            break
        reports.extend(page)

        # a short page means that was the last one
        if len(page) < page_size:
            break

        # openfda rejects skip above 25000
        if len(reports) + page_size > MAX_SKIP:
            break

    return reports[:limit]
