import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "blocca", Path(__file__).parent.parent / "hooks" / "blocca_scritture.py"
)
blocca = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blocca)

META = "mcp__abc-123__"

BLOCKED = [
    "ads_create_campaign", "ads_update_entity", "ads_activate_entity", "ads_duplicate_entity",
    "ads_creative_delete", "ads_creative_upload_media", "ads_create_upload_url",
    "ads_finalize_upload", "ads_catalog_product_feed_delete", "ads_catalog_event_source_connect",
    "ads_pixel_event_create", "ads_experiment_lift_create_test", "ads_boost_ig_post",
    "ads_permission_preview_set_asset_permissions", "ads_dataset_update_automatic_matching",
    "ads_some_future_tool",
]
ALLOWED = [
    "ads_get_ad_entities", "ads_get_ad_accounts", "ads_insights_performance_trend",
    "ads_catalog_list_products", "ads_catalog_get_product_feed_upload_sessions",
    "ads_catalog_event_source_get_health", "ads_pixel_event_read", "ads_experiment_list_tests",
    "ads_experiment_abtest_get_test", "ads_library_search", "offer_report",
]


def test_meta_write_blocked():
    for t in BLOCKED:
        assert blocca.is_blocked(META + t), t


def test_meta_read_allowed():
    for t in ALLOWED:
        assert not blocca.is_blocked(META + t), t


def test_google():
    assert not blocca.is_blocked("mcp__gads__search_search")
    assert blocca.is_blocked("mcp__8471875c-2b1b__campaigns_mutate")
    assert blocca.is_blocked("mcp__8471875c-2b1b__update_campaign_budget")


def test_app_tools_untouched():
    assert not blocca.is_blocked("mcp__ccd_sidebar__create_group")


def test_non_mcp_untouched():
    assert not blocca.is_blocked("Bash")
    assert not blocca.is_blocked("Read")
