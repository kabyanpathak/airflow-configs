"""Browser smoke test for the current login-disabled UI, with no DAG execution."""

import os
import re

from playwright.sync_api import expect, sync_playwright


def test_dag_list_and_navigation():
    base_url = os.environ["AIRFLOW_TEST_URL"]
    errors = []
    expect.set_options(timeout=30_000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("requestfailed", lambda request: errors.append(
            f"Request failed: {request.url}: {request.failure}"
        ) if request.url.startswith(base_url) else None)
        page.on("response", lambda response: errors.append(
            f"HTTP {response.status}: {response.url}"
        ) if response.url.startswith(base_url) and response.status >= 400 else None)
        try:
            with page.expect_response(
                lambda response: response.url.startswith(base_url + "/ui/dags?")
            ) as dag_list:
                response = page.goto(base_url + "/dags")
            assert response is not None and response.ok
            assert dag_list.value.ok
            expect(page.get_by_role("textbox", name="Search Dags", exact=False)).to_be_visible()
            expect(page.get_by_role("heading", name=re.compile(r"^[\d,]+ Dags$"))).to_be_visible()
            # Works whether the list is populated or empty.
            page.get_by_role("link", name="Home", exact=True).first.click()
            expect(page).to_have_url(re.compile(re.escape(base_url) + r"/?$"))
            expect(page.get_by_role("heading", name="Welcome", exact=True)).to_be_visible()
            expect(page.get_by_role("heading", name="Health", exact=True)).to_be_visible()
            page.wait_for_load_state("networkidle")
            assert not errors, "\n".join(errors)
        finally:
            browser.close()
