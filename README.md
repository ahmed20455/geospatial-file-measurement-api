# Geospatial File Measurement API

A FastAPI backend for uploading geospatial files, extracting their features, and calculating area and length measurements with appropriate coordinate reference system handling.

## Overview

This project was built as part of a backend assignment focused on geospatial data processing, API design, file validation, and reliable measurement calculations.

The API accepts KML files and ZIP archives containing a Shapefile. Once a file is uploaded, it reads the spatial data, extracts feature geometries and their attributes, and calculates measurements for supported geometry types.

One important detail in geospatial processing is that coordinates are not always expressed in metres. For example, EPSG:4326 represents locations using longitude and latitude in degrees. Calculating area or distance directly from these coordinates would produce misleading results. This implementation transforms geometries to a suitable projected CRS before calculating measurements.

The focus was not just on getting valid files to work, but also on handling malformed input, incomplete Shapefiles, unsupported geometries, and unsafe ZIP archives without bringing down the application.

## Features

* Upload KML files and ZIP archives containing a Shapefile.
* Extract feature IDs, geometry types, geometries, CRS information, and properties.
* Calculate polygon and multipolygon areas in square metres.
* Calculate line and multiline lengths in metres.
* Handle point geometries without performing unnecessary measurements.
* Handle empty and unsupported geometries gracefully.
* Transform geographic coordinates to a projected CRS before measurement.
* Convert measurements from supported projected CRS units to metres.
* Validate required Shapefile components and reject archives containing multiple Shapefiles.
* Enforce upload-size, archive-member-count, and uncompressed-size limits.
* Reject unsafe ZIP paths and symbolic links.
* Clean up temporary upload files, including when processing fails.
* Convert non-JSON-native property values into JSON-safe representations.
* Return structured API responses and meaningful HTTP errors.

## Tech stack

| Technology         | Purpose                                           |
| ------------------ | ------------------------------------------------- |
| Python             | Core implementation                               |
| FastAPI            | REST API and request handling                     |
| GeoPandas          | Reading and processing geospatial files           |
| Shapely            | Geometry operations and measurements              |
| PyProj             | CRS interpretation and coordinate transformations |
| Pydantic           | Response validation and schema definition         |
| pytest             | Automated testing                                 |
| FastAPI TestClient | Testing API endpoints                             |

## Getting started

### Prerequisites

* Python 3.12 or a compatible Python version.
* [uv](https://docs.astral.sh/uv/) for dependency and environment management, if using the project's existing `pyproject.toml` and lockfile.

### 1. Clone the repository

```bash
git clone <https://github.com/ahmed20455/geospatial-file-measurement-api>
cd <geospatial-file-measurement-api>
```


### 2. Install dependencies

If the repository contains `pyproject.toml` and `uv.lock`, run:

```bash
uv sync
```

If you are using a different dependency-management setup, install the packages listed in your project's dependency file instead.

### 3. Start the application

```bash
uv run uvicorn main:app --reload
```

The API will normally be available at:

```text
http://127.0.0.1:8000
```

### 4. Explore the API

Open the interactive Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

You can upload files, inspect responses, and test the available endpoints directly from your browser.

## API documentation

All endpoints use the `/api/files` base path. The implementation uses these paths without requiring a trailing slash.

### 1. Upload a geospatial file

**`POST /api/files`**

Uploads and processes a KML file or a ZIP archive containing a Shapefile.

**Request:** `multipart/form-data`

| Field  | Type | Description                                        |
| ------ | ---- | -------------------------------------------------- |
| `file` | File | A `.kml` file or a `.zip` containing one Shapefile |

Example using curl:

```bash
curl -X POST \
  "http://127.0.0.1:8000/api/files" \
  -F "file=@survey.kml"
```

Example successful response (`201 Created`):

```json
{
  "id": "abc123-example-file-id",
  "filename": "survey.kml",
  "feature_count": 120,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

The ID is generated for each upload and is used to retrieve the processed file information and measurements.

The API rejects unsupported extensions, invalid or incomplete input files, files without features, missing CRS information, and uploads that exceed the configured size limit.

### 2. Retrieve file information

**`GET /api/files/{file_id}`**

Returns the metadata associated with a previously processed file.

Example:

```bash
curl "http://127.0.0.1:8000/api/files/abc123-example-file-id"
```

Example response (`200 OK`):

```json
{
  "id": "abc123-example-file-id",
  "filename": "survey.kml",
  "feature_count": 120,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

Returns `404 Not Found` when the supplied ID does not exist in the current application process.

### 3. Retrieve all extracted features

**`GET /api/files/{file_id}/features`**

This is an additional endpoint beyond the minimum requirements. It returns the complete feature data, including geometry and properties.

Example:

```bash
curl "http://127.0.0.1:8000/api/files/abc123-example-file-id/features"
```

Example response (shortened for readability):

```json
[
  {
    "feature_id": 0,
    "geometry_type": "Polygon",
    "geometry": {
      "type": "Polygon",
      "coordinates": [
        [
          [78.0, 17.0],
          [78.01, 17.0],
          [78.01, 17.01],
          [78.0, 17.01],
          [78.0, 17.0]
        ]
      ]
    },
    "crs": "EPSG:4326",
    "properties": {
      "name": "Sample area"
    },
    "measurement": {
      "type": "area",
      "value": 1140000.0,
      "unit": "m²",
      "crs": "EPSG:32644",
      "status": null
    }
  }
]
```

The geometry coordinates and measurement values above are illustrative, not a guaranteed result for this sample polygon.

Each feature includes its original geometry and CRS, its attributes, and its measurement result. The endpoint returns all features in one response, so large datasets can produce relatively large JSON payloads.

### 4. Retrieve measurements

**`GET /api/files/{file_id}/measurements`**

Returns measurement information for all features in the uploaded file, without including the full geometry coordinates and property dictionaries.

Example:

```bash
curl "http://127.0.0.1:8000/api/files/abc123-example-file-id/measurements"
```

Example response:

```json
{
  "file_id": "abc123-example-file-id",
  "filename": "survey.kml",
  "features": [
    {
      "feature_id": 0,
      "geometry_type": "Polygon",
      "measurement": {
        "type": "area",
        "value": 1140000.0,
        "unit": "m²",
        "crs": "EPSG:32644",
        "status": null
      }
    },
    {
      "feature_id": 1,
      "geometry_type": "LineString",
      "measurement": {
        "type": "length",
        "value": 850.0,
        "unit": "m",
        "crs": "EPSG:32644",
        "status": null
      }
    },
    {
      "feature_id": 2,
      "geometry_type": "Point",
      "measurement": {
        "type": null,
        "value": null,
        "unit": null,
        "crs": null,
        "status": "NOT_REQUIRED"
      }
    }
  ]
}
```

The measurement values and CRS identifiers in this example are illustrative. Actual results depend on the uploaded geometries and their source CRS.

### Measurement result statuses

| Status                 | Meaning                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| `EMPTY_GEOMETRY`       | The feature has no usable geometry.                                |
| `NOT_REQUIRED`         | The geometry is a point, for which no measurement is required.     |
| `UNSUPPORTED_GEOMETRY` | The geometry type is not supported for area or length calculation. |

For supported geometries, the measurement response includes a type (`area` or `length`), a numeric value, its unit, and the projected CRS used for the calculation.

## Architecture and processing flow

The application is intentionally kept in a small, function-based structure. File handling, validation, geometry processing, measurement calculation, and API routing are separated into functions within `main.py`.

### File-processing flow

1. **Receive the upload:** The upload endpoint validates the filename extension and saves the incoming file to a temporary location in chunks.
2. **Validate the input:** ZIP archives are checked for required Shapefile components, multiple Shapefiles, unsafe paths, excessive archive contents, and symbolic links.
3. **Read the spatial data:** GeoPandas reads the KML or extracted Shapefile into a GeoDataFrame.
4. **Validate the dataset:** Empty datasets and files without a CRS are rejected.
5. **Process each feature:** The application extracts its ID, geometry type, geometry, CRS, and attributes, then calculates the appropriate measurement.
6. **Store the result:** A UUID is assigned to the processed file, and its metadata and feature results are stored for subsequent requests.
7. **Clean up:** Temporary upload files are deleted after processing, including when an exception occurs. Extracted ZIP contents are managed inside a temporary directory.

### Measurement calculation flow

The `calculate_measurement()` function determines what calculation is appropriate for each geometry.

* **Polygon / MultiPolygon:** Calculate area after projection and return the result in square metres.
* **LineString / MultiLineString:** Calculate length after projection and return the result in metres.
* **Point:** Return `NOT_REQUIRED`.
* **Empty geometry:** Return `EMPTY_GEOMETRY`.
* **Other geometry types:** Return `UNSUPPORTED_GEOMETRY`.

This keeps unsupported input from causing the entire request to fail unnecessarily.

### CRS handling

Coordinate reference system handling is one of the most important parts of this implementation.

For geographic input such as EPSG:4326, the application selects a UTM zone based on a representative point of the geometry. It chooses a northern or southern UTM CRS based on the point's latitude and transforms the geometry using PyProj and Shapely.

For an already projected CRS, the existing CRS is used. Its axis unit conversion factor is applied so that supported measurements are returned in metres or square metres, including when the projected CRS uses feet.

This approach is practical for local and regional datasets. It is not intended to be universally optimal for geometries spanning multiple UTM zones, crossing the antimeridian, or lying outside normal UTM coverage.

## Design decisions

### Why FastAPI?

FastAPI provides a straightforward way to build REST endpoints, validate response structures with Pydantic, and expose interactive API documentation. It also works well with the Python geospatial ecosystem used in this project.

### Why GeoPandas, Shapely, and PyProj?

Each library has a distinct responsibility:

* GeoPandas reads and organizes geospatial features and their attributes.
* Shapely provides geometry operations, including area and length calculations.
* PyProj handles CRS interpretation and coordinate transformations.

Using these libraries avoids implementing geometry parsing and projection mathematics from scratch.

### Why use temporary files?

Geospatial libraries often work naturally with file paths, and Shapefiles consist of multiple related files. Streaming uploads to a temporary file also avoids loading the entire uploaded file into application memory at once.

The implementation enforces upload and archive size limits and removes temporary files after processing.

### Why validate ZIP archives?

A ZIP extension alone does not establish that an archive contains a valid Shapefile. The application checks for one `.shp` file and its required `.shx` and `.dbf` companion files, while also rejecting unsafe paths and symbolic links.

The archive member count and total uncompressed size are limited to reduce the risk of excessive resource consumption.

### Why store results in memory?

For this assignment, an in-memory dictionary keyed by UUID keeps the implementation simple and avoids introducing database infrastructure that the core requirements do not need.

The trade-off is that records disappear when the application restarts, and this storage approach is not suitable for a multi-worker or persistent production deployment.

### Why handle unsupported geometries explicitly?

Not every geometry requires the same calculation. Returning an explicit status for points, empty geometries, and unsupported types makes the API response predictable and prevents a single unsupported feature from unnecessarily breaking the entire dataset.

## Testing

The project includes **28 passing automated tests** covering the main processing paths, measurement calculations, input validation, and error handling.

Run the test suite with:

```bash
uv run python -m pytest -v
```

The tests cover:

* Successful KML and Shapefile ZIP uploads.
* Unsupported extensions and invalid file contents.
* Missing or incomplete Shapefile components.
* Missing CRS information and missing file IDs.
* Polygon area and line length calculations.
* MultiPolygon and MultiLineString measurements.
* Point, empty, and unsupported geometries.
* Projection of geographic coordinates.
* Conversion from feet to metric measurement units.
* Upload-size, ZIP-member-count, and uncompressed-size limits.
* ZIP path-traversal rejection.
* Temporary-file cleanup after processing failures.
* JSON-safe conversion of properties such as NumPy values, NaN, and dates.

The tests use generated sample geometries and ZIP archives where possible, allowing the suite to run without depending on external geospatial datasets.

The current suite passes in the development environment. As with any test suite, this confirms the tested scenarios rather than every possible real-world geometry or malformed input.

## Limitations and future scope

There are a few areas I would improve if this were developed beyond the assignment.

* **Persistent storage:** Replace the in-memory dictionary with a database and persistent file storage so results survive application restarts.
* **Pagination:** Add pagination to the full features endpoint for large datasets. Currently, it returns every feature, including full geometry coordinates, in one response.
* **Improved CRS selection:** Use a more robust projection strategy for geometries spanning large areas, multiple UTM zones, or unusual geographic regions.
* **Background processing:** Move expensive file processing to background workers for larger datasets and longer-running jobs.
* **Stronger input controls:** Add additional validation and resource controls for complex geometries and potentially expensive processing operations.
* **Expanded test coverage:** Add tests for more CRS types, boundary cases near UTM zone limits, unusual geometries, and larger datasets.
* **Production deployment:** Add structured logging, configuration through environment variables, monitoring, and appropriate concurrency controls.

These improvements would make the service more suitable for sustained use with larger datasets and multiple concurrent users.

## What I learned

Working on this project reinforced that geospatial processing involves more than reading a file and calling an area or length function. The CRS determines how coordinates should be interpreted, geometry types determine which calculations are meaningful, and file-processing code needs to account for malformed data and resource limits.

It also highlighted the importance of testing failure cases, not just successful uploads. Validating archive contents, cleaning up temporary files, converting attributes into JSON-safe values, and returning predictable error responses all contribute to making a backend service more reliable.

## Project status

The core assignment requirements are implemented, and the current automated test suite passes all 28 tests.

The project is a focused backend implementation intended to demonstrate API development, geospatial data handling, measurement calculations, input validation, and testing. The limitations above identify areas for further development rather than features already implemented.

## License

No license has been specified yet. Add a license if you intend to permit reuse or distribution of the project.
