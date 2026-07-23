"""Category-specific attribute validation + schema inheritance."""
import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from apps.catalog.models import Category
from apps.catalog.services import validate_attributes, validate_category_depth


@pytest.mark.django_db
def test_effective_schema_inherits_and_overrides(root_category):
    # root_category is Phones (child of Electronics). It should see Electronics'
    # required "brand" plus its own fields.
    keys = {f["key"] for f in root_category.effective_schema()}
    assert {"brand", "storage_gb", "network", "dual_sim"} <= keys


@pytest.mark.django_db
def test_required_inherited_field_enforced(root_category):
    with pytest.raises(ValidationError) as exc:
        validate_attributes(root_category, {"storage_gb": 128})
    assert "brand" in exc.value.detail["attributes"]


@pytest.mark.django_db
def test_unknown_key_rejected(root_category):
    with pytest.raises(ValidationError) as exc:
        validate_attributes(root_category, {"brand": "Apple", "color": "red"})
    assert "color" in exc.value.detail["attributes"]


@pytest.mark.django_db
def test_type_coercion_and_validation(root_category):
    cleaned = validate_attributes(
        root_category,
        {"brand": "Apple", "storage_gb": "128", "network": "Unlocked", "dual_sim": "true"},
    )
    assert cleaned["storage_gb"] == 128
    assert cleaned["dual_sim"] is True
    assert cleaned["brand"] == "Apple"


@pytest.mark.django_db
def test_bad_number_rejected(root_category):
    with pytest.raises(ValidationError) as exc:
        validate_attributes(root_category, {"brand": "Apple", "storage_gb": "lots"})
    assert "storage_gb" in exc.value.detail["attributes"]


@pytest.mark.django_db
def test_enum_out_of_range_rejected(root_category):
    with pytest.raises(ValidationError) as exc:
        validate_attributes(root_category, {"brand": "Apple", "network": "5G"})
    assert "network" in exc.value.detail["attributes"]


@pytest.mark.django_db
def test_boolean_is_not_a_number(root_category):
    with pytest.raises(ValidationError) as exc:
        validate_attributes(root_category, {"brand": "Apple", "storage_gb": True})
    assert "storage_gb" in exc.value.detail["attributes"]


@pytest.mark.django_db
def test_empty_optional_values_dropped(root_category):
    cleaned = validate_attributes(root_category, {"brand": "Apple", "storage_gb": ""})
    assert "storage_gb" not in cleaned


@pytest.mark.django_db
def test_category_depth_limit():
    a = Category.objects.create(name="A", slug="a")
    b = Category.objects.create(name="B", slug="b", parent=a)
    c = Category.objects.create(name="C", slug="c", parent=b)
    validate_category_depth(c)  # depth 3 is fine
    d = Category.objects.create(name="D", slug="d", parent=c)
    with pytest.raises(DjangoValidationError):
        validate_category_depth(d)  # depth 4 is not
