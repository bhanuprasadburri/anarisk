from app.services.email import (
    render_generic_email,
    render_otp_email,
    render_registration_notice_email,
    render_reset_email,
)
from app.services.evidence import _csv_safe as evidence_csv_safe
from app.services.reports import _csv_safe as report_csv_safe


def test_user_supplied_template_values_are_html_escaped():
    payload = '<img src=x onerror="alert(1)">'
    for rendered in (
        render_otp_email(payload, "123456", 10)[2],
        render_registration_notice_email(payload, payload)[2],
        render_reset_email(payload, "https://example.com/reset?a=1&b=2", 30)[2],
        render_generic_email(payload, payload, payload)[2],
    ):
        assert "<img" not in rendered
        assert "&lt;img" in rendered


def test_reset_link_is_attribute_escaped():
    html = render_reset_email("Ana", 'https://example.com/reset?x=" onmouseover="alert(1)', 30)[2]
    assert 'href="https://example.com/reset?x=&quot; onmouseover=&quot;alert(1)' in html


def test_csv_exports_neutralize_spreadsheet_formulas():
    for safe in (evidence_csv_safe, report_csv_safe):
        assert safe("=1+1") == "'=1+1"
        assert safe("  @SUM(A1:A2)") == "'  @SUM(A1:A2)"
        assert safe("ordinary text") == "ordinary text"


def test_ai_credentials_are_not_bundled_as_defaults():
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    assert settings.ai_api_key == ""
