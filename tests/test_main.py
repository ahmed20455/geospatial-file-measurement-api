
from datetime import datetime
import io
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pyproj import CRS
from shapely.geometry import (
    Polygon,
    LineString,
    MultiPoint,
    Point,
    MultiPolygon,
    MultiLineString,
    box,
)

import main
from main import (
    app,
    calculate_measurement,
    process_features,
    extract_zip_safely,
)

client = TestClient(app)


# --------------------------------------------------
# Helper for generating valid Shapefile ZIP files
# --------------------------------------------------

def create_shapefile_zip(tmp_path, basename="test"):
    shapefile_dir = tmp_path / f"shape_{basename}"
    shapefile_dir.mkdir()

    polygon = Polygon([
        (78.0, 17.0),
        (78.01, 17.0),
        (78.01, 17.01),
        (78.0, 17.01),
        (78.0, 17.0),
    ])

    gdf = gpd.GeoDataFrame(
        {"name": ["Test polygon"]},
        geometry=[polygon],
        crs="EPSG:4326",
    )

    shp_path = shapefile_dir / f"{basename}.shp"
    gdf.to_file(shp_path)

    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        for path in shapefile_dir.iterdir():
            archive.write(path, arcname=path.name)

    return buffer.getvalue()


# --------------------------------------------------
# Existing tests: 1–14
# --------------------------------------------------

def test_unsupported_file_type():
    response = client.post(
        "/api/files",
        files={
            "file": (
                "document.txt",
                b"hello",
                "text/plain",
            )
        },
    )

    assert response.status_code == 400


def test_file_not_found():
    response = client.get("/api/files/nonexistent-id")

    assert response.status_code == 404


def test_successful_kml_upload():
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark>
          <name>Test polygon</name>
          <Polygon>
            <outerBoundaryIs>
              <LinearRing>
                <coordinates>
                  78.0,17.0,0
                  78.01,17.0,0
                  78.01,17.01,0
                  78.0,17.01,0
                  78.0,17.0,0
                </coordinates>
              </LinearRing>
            </outerBoundaryIs>
          </Polygon>
        </Placemark>
      </Document>
    </kml>
    """

    response = client.post(
        "/api/files",
        files={
            "file": (
                "test.kml",
                kml_content.encode("utf-8"),
                "application/vnd.google-earth.kml+xml",
            )
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["filename"] == "test.kml"
    assert data["feature_count"] == 1
    assert data["status"] == "COMPLETED"

    file_id = data["id"]

    measurements_response = client.get(
        f"/api/files/{file_id}/measurements"
    )

    assert measurements_response.status_code == 200

    measurement = measurements_response.json()["features"][0]["measurement"]

    assert measurement["type"] == "area"
    assert measurement["value"] > 0
    assert measurement["unit"] == "m²"


def test_line_length_measurement():
    line = LineString([
        (78.0, 17.0),
        (78.01, 17.0),
    ])

    result = calculate_measurement(line, "EPSG:4326")

    assert result["type"] == "length"
    assert result["value"] > 0
    assert result["unit"] == "m"
    assert result["crs"] is not None


def test_zip_without_shapefile():
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "This is not a Shapefile.")

    response = client.post(
        "/api/files",
        files={
            "file": (
                "invalid.zip",
                buffer.getvalue(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 400


def test_successful_shapefile_zip_upload(tmp_path):
    zip_content = create_shapefile_zip(tmp_path)

    response = client.post(
        "/api/files",
        files={
            "file": (
                "test.zip",
                zip_content,
                "application/zip",
            )
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["feature_count"] == 1
    assert data["status"] == "COMPLETED"

    file_id = data["id"]

    features_response = client.get(
        f"/api/files/{file_id}/features"
    )

    assert features_response.status_code == 200

    features = features_response.json()

    assert len(features) == 1
    assert features[0]["geometry_type"] == "Polygon"
    assert features[0]["properties"]["name"] == "Test polygon"
    assert features[0]["measurement"]["type"] == "area"
    assert features[0]["measurement"]["value"] > 0


def test_incomplete_shapefile_zip():
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("test.shp", b"fake shapefile data")

    response = client.post(
        "/api/files",
        files={
            "file": (
                "incomplete.zip",
                buffer.getvalue(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 400
    assert "incomplete" in response.json()["detail"].lower()


def test_missing_crs():
    polygon = Polygon([
        (0, 0),
        (1, 0),
        (1, 1),
        (0, 1),
        (0, 0),
    ])

    gdf = gpd.GeoDataFrame(
        {"name": ["Unknown CRS"]},
        geometry=[polygon],
    )

    with pytest.raises(HTTPException) as exc_info:
        process_features(gdf)

    assert exc_info.value.status_code == 400
    assert "CRS" in exc_info.value.detail


def test_uploaded_temp_file_is_cleaned_up(monkeypatch):
    captured = {}

    async def fake_save_upload(file):
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            temp.write(b"test")
            captured["path"] = Path(temp.name)

        return captured["path"]

    def fake_process_file(file_path):
        raise HTTPException(
            status_code=400,
            detail="Simulated processing failure",
        )

    monkeypatch.setattr(main, "save_upload", fake_save_upload)
    monkeypatch.setattr(main, "process_file", fake_process_file)

    response = client.post(
        "/api/files",
        files={
            "file": (
                "test.kml",
                b"test data",
                "application/vnd.google-earth.kml+xml",
            )
        },
    )

    assert response.status_code == 400
    assert not captured["path"].exists()


def test_zip_path_traversal_rejected(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    destination = tmp_path / "extracted"
    destination.mkdir()

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../outside.txt", "unsafe content")

    with pytest.raises(HTTPException) as exc_info:
        extract_zip_safely(zip_path, destination)

    assert exc_info.value.status_code == 400
    assert not (tmp_path / "outside.txt").exists()


def test_area_conversion_from_feet_to_square_metres():
    source_crs = CRS.from_epsg(2263)

    polygon = box(
        1000000,
        200000,
        1000010,
        200010,
    )

    result = calculate_measurement(polygon, source_crs)

    assert result["type"] == "area"
    assert result["unit"] == "m²"

    expected_area = 100 * (1200 / 3937) ** 2

    assert abs(result["value"] - expected_area) < 1e-6


def test_empty_geometry():
    empty_polygon = Polygon()

    result = calculate_measurement(
        empty_polygon,
        "EPSG:4326",
    )

    assert result["status"] == "EMPTY_GEOMETRY"
    assert result["value"] is None


def test_unsupported_geometry():
    geometry = MultiPoint([
        (78.0, 17.0),
        (78.01, 17.01),
    ])

    result = calculate_measurement(
        geometry,
        "EPSG:4326",
    )

    assert result["status"] == "UNSUPPORTED_GEOMETRY"
    assert result["value"] is None


def test_oversized_upload_rejected(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_SIZE", 4)

    response = client.post(
        "/api/files",
        files={
            "file": (
                "test.kml",
                b"12345",
                "application/vnd.google-earth.kml+xml",
            )
        },
    )

    assert response.status_code == 413


# --------------------------------------------------
# New tests: malformed input and ZIP validation
# --------------------------------------------------

def test_malformed_kml_rejected():
    response = client.post(
        "/api/files",
        files={
            "file": (
                "broken.kml",
                b"<kml><Document><Placemark>",
                "application/vnd.google-earth.kml+xml",
            )
        },
    )

    assert 400 <= response.status_code < 500


def test_corrupted_zip_rejected():
    response = client.post(
        "/api/files",
        files={
            "file": (
                "corrupted.zip",
                b"This is not a ZIP archive",
                "application/zip",
            )
        },
    )

    assert response.status_code == 400


def test_missing_filename_rejected():
    response = client.post(
        "/api/files",
        files={
            "file": (
                "",
                b"test content",
                "application/octet-stream",
            )
        },
    )

    assert response.status_code in (400, 413, 422)


@pytest.mark.parametrize(
    "members",
    [
        ["test.shp", "test.dbf"],
        ["test.shp", "test.shx"],
    ],
)
def test_missing_required_shapefile_component_rejected(members):
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        for member in members:
            archive.writestr(member, b"placeholder")

    response = client.post(
        "/api/files",
        files={
            "file": (
                "incomplete.zip",
                buffer.getvalue(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 400


def test_zip_member_limit_enforced(tmp_path, monkeypatch):
    zip_content = create_shapefile_zip(tmp_path, "member_limit")

    # A valid Shapefile ZIP contains multiple component files.
    monkeypatch.setattr(main, "MAX_ZIP_MEMBERS", 1)

    response = client.post(
        "/api/files",
        files={
            "file": (
                "member_limit.zip",
                zip_content,
                "application/zip",
            )
        },
    )

    assert response.status_code == 400


def test_zip_uncompressed_size_limit_enforced(tmp_path, monkeypatch):
    zip_content = create_shapefile_zip(tmp_path, "size_limit")

    monkeypatch.setattr(main, "MAX_UNCOMPRESSED_SIZE", 1)

    response = client.post(
        "/api/files",
        files={
            "file": (
                "size_limit.zip",
                zip_content,
                "application/zip",
            )
        },
    )

    assert response.status_code in (400,413)


# --------------------------------------------------
# New tests: geometry handling
# --------------------------------------------------

def test_point_geometry_requires_no_measurement():
    result = calculate_measurement(
        Point(78.0, 17.0),
        "EPSG:4326",
    )

    assert result["status"] == "NOT_REQUIRED"
    assert result["value"] is None


def test_multipolygon_area_measurement():
    geometry = MultiPolygon([
        box(78.0, 17.0, 78.01, 17.01),
        box(78.02, 17.0, 78.03, 17.01),
    ])

    result = calculate_measurement(
        geometry,
        "EPSG:4326",
    )

    assert result["type"] == "area"
    assert result["value"] > 0
    assert result["unit"] == "m²"


def test_multilinestring_length_measurement():
    geometry = MultiLineString([
        [(78.0, 17.0), (78.01, 17.0)],
        [(78.02, 17.0), (78.03, 17.0)],
    ])

    result = calculate_measurement(
        geometry,
        "EPSG:4326",
    )

    assert result["type"] == "length"
    assert result["value"] > 0
    assert result["unit"] == "m"


def test_geographic_coordinates_are_projected():
    line = LineString([
        (78.0, 17.0),
        (78.01, 17.0),
    ])

    result = calculate_measurement(line, "EPSG:4326")

    assert result["type"] == "length"
    assert result["value"] > 0
    assert result["crs"] != "EPSG:4326"


# --------------------------------------------------
# New tests: endpoint error handling
# --------------------------------------------------

def test_features_endpoint_file_not_found():
    response = client.get(
        "/api/files/nonexistent-id/features"
    )

    assert response.status_code == 404


def test_measurements_endpoint_file_not_found():
    response = client.get(
        "/api/files/nonexistent-id/measurements"
    )

    assert response.status_code == 404


# --------------------------------------------------
# New tests: JSON-safe feature properties
# --------------------------------------------------

def test_feature_properties_are_json_safe():
    polygon = Polygon([
        (0, 0),
        (1, 0),
        (1, 1),
        (0, 1),
        (0, 0),
    ])

    gdf = gpd.GeoDataFrame(
        {
            "count": [np.int64(7)],
            "score": [float("nan")],
            "created": [datetime(2024, 1, 1)],
        },
        geometry=[polygon],
        crs="EPSG:4326",
    )

    features = process_features(gdf)

    properties = features[0]["properties"]

    assert properties["count"] == 7
    assert properties["score"] is None
    assert properties["created"].startswith("2024-01-01")