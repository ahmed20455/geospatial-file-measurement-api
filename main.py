from pathlib import Path, PurePosixPath
from fastapi import FastAPI, UploadFile, HTTPException, status
import tempfile
import geopandas as gpd
import zipfile
from shapely.geometry import mapping
from pyproj import CRS, Transformer
from shapely.ops import transform
import uuid
from typing import Any, Literal
from pydantic import BaseModel
import math
import numpy as np
import pandas as pd
from datetime import date,datetime


app = FastAPI()


files_store={}

ALLOWED_EXTENSIONS = {".kml",".zip"}
MAX_UNCOMPRESSED_SIZE = 500 * 1024 * 1024  # 500 MiB
MAX_ZIP_MEMBERS = 10_000
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MiB
CHUNK_SIZE = 1024 * 1024             # 1 MiB

class FileInfoResponse(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: str
    status: Literal["COMPLETED"]


class MeasurementResponse(BaseModel):
    type: Literal["area","length"] | None = None
    value: float | None = None
    unit: str | None = None
    crs: str | None = None
    status: Literal[
        "EMPTY_GEOMETRY",
        "NOT_REQUIRED",
        "UNSUPPORTED_GEOMETRY"
    ] | None = None


class FeatureResponse(BaseModel):
    feature_id: int | str
    geometry_type: str | None
    geometry: dict[str,Any] | None
    crs: str | None
    properties: dict[str, Any]
    measurement: MeasurementResponse


class MeasurementFeatureResponse(BaseModel):
    feature_id: int | str
    geometry_type: str | None
    measurement: MeasurementResponse


class MeasurementsResponse(BaseModel):
    file_id: str
    filename: str
    features: list[MeasurementFeatureResponse]


def read_geospatial_file(file_path: Path):
    try:
        return gpd.read_file(file_path)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unable to read the geospatial file. "
                "Check that the file is valid and supported."
            ),
        ) from exc


def process_file(file_path: Path):
    if file_path.suffix == ".kml":
        gdf = read_geospatial_file(file_path)

    elif file_path.suffix == ".zip":
        if not zipfile.is_zipfile(file_path):
            raise HTTPException(
                status_code=400,
                detail="The uploaded .zip file is not a valid ZIP archive."
            )

        shp_path = validate_shapefile_zip(file_path)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)

            extract_zip_safely(
                file_path,
                temp_dir_path
            )

            extracted_shp = temp_dir_path / shp_path

            gdf = read_geospatial_file(extracted_shp)

    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported geospatial file."
        )

    if gdf.empty:
        raise HTTPException(
            status_code=400,
            detail="The uploaded geospatial file contains no features."
        )

    features = process_features(gdf)

    return gdf, features


def validate_extension(file:UploadFile):
    extension = Path(file.filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a .kml file or a .zip containing a Shapefile "
        )


async def save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename).suffix.lower()
    temp_path = None
    total_size = 0

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix
        ) as temp_file:
            temp_path = Path(temp_file.name)

            while chunk := await file.read(CHUNK_SIZE):
                total_size += len(chunk)

                if total_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="Uploaded file exceeds the 100 MiB size limit."
                    )

                temp_file.write(chunk)

        return temp_path

    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    finally:
        await file.close()


def validate_shapefile_zip(file_path: Path) -> Path:
    try:
        with zipfile.ZipFile(file_path, "r") as zip_file:
            members = zip_file.infolist()

            # Ignore directory entries and normalize ZIP paths.
            files = []

            for member in members:
                if member.is_dir():
                    continue
                if "\\" in member.filename:
                    raise HTTPException(
                        status_code=400,
                        detail="The ZIP contains an invalid file path."
                    )
                normalized = PurePosixPath(
                    member.filename.replace("\\", "/")
                )

                # Reject absolute paths and parent-directory traversal.
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise HTTPException(
                        status_code=400,
                        detail="The ZIP contains an unsafe file path."
                    )

                # Remove harmless "." path components.
                normalized = PurePosixPath(
                    *[part for part in normalized.parts if part != "."]
                )

                files.append((member.filename, normalized))

            # Find Shapefiles, regardless of extension casing.
            shp_files = [
                normalized
                for _, normalized in files
                if normalized.suffix.casefold() == ".shp"
            ]

            if not shp_files:
                raise HTTPException(
                    status_code=400,
                    detail="The ZIP file does not contain a Shapefile."
                )

            if len(shp_files) > 1:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "The ZIP contains multiple Shapefiles. "
                        "Please upload a ZIP containing one Shapefile."
                    )
                )

            shp_path = shp_files[0]
            shp_parent = tuple(
                part.casefold() for part in shp_path.parts[:-1]
            )
            shp_stem = shp_path.stem.casefold()

            # Match companion files in the same directory, ignoring case.
            available = set()

            for _, path in files:
                parent = tuple(
                    part.casefold() for part in path.parts[:-1]
                )
                stem = path.stem.casefold()
                suffix = path.suffix.casefold()

                if parent == shp_parent and stem == shp_stem:
                    available.add(suffix)

            required = {".shp", ".shx", ".dbf"}
            missing = required - available

            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "The Shapefile is incomplete. Missing: "
                        + ", ".join(sorted(missing))
                    )
                )

            # Preserve the archive's normalized relative path for extraction.
            return Path(*shp_path.parts)

    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=400,
            detail="The uploaded ZIP archive is corrupted or invalid."
        )


def get_utm_crs(geometry,source_crs):
    source = CRS.from_user_input(source_crs)

    if source.is_projected:
        return source
    
    point = geometry.representative_point()

    zone = int((point.x+180)//6)+1
    
    if point.y>=0:
        epsg = 32600+ zone
    else:
        epsg = 32700 + zone

    return CRS.from_epsg(epsg)


def project_geometry(geometry,source_crs):
    target_crs = get_utm_crs(geometry, source_crs)

    transformer = Transformer.from_crs(
        source_crs,
        target_crs,
        always_xy=True
    )

    projected_geometry=transform(
        transformer.transform,
        geometry
    )

    return projected_geometry,target_crs


def calculate_measurement(geometry,source_crs):
    if geometry is None or geometry.is_empty:
        return {
            "type": None,
            "value": None,
            "unit": None,
            "status": "EMPTY_GEOMETRY"
        }

    geometry_type = geometry.geom_type.replace(" Z", "")

    if geometry_type == "Point":
        return {
            "type": None,
            "value": None,
            "unit": None,
            "status": "NOT_REQUIRED"
        }
    
    if geometry_type not in {
        "Polygon",
        "MultiPolygon",
        "LineString",
        "MultiLineString"
    }:
        return {
            "type": None,
            "value": None,
            "unit": None,
            "status": "UNSUPPORTED_GEOMETRY"
        }

    projected_geometry,projected_crs = project_geometry(
        geometry,
        source_crs
    )
  
    unit_to_metre = projected_crs.axis_info[0].unit_conversion_factor

    if unit_to_metre is None:
        raise HTTPException(
            status_code=400,
            detail="Unsupported projected CRS units."
        )
    if geometry_type in {"Polygon","MultiPolygon"}:
        return{
            "type":"area",
            "value":projected_geometry.area*(unit_to_metre**2),
            "unit":"m²",
            "crs":projected_crs.to_string()
        }
    
    if geometry_type in {"LineString","MultiLineString"}:
        return {
            "type":"length",
            "value":projected_geometry.length*unit_to_metre,
            "unit":"m",
            "crs":projected_crs.to_string()
        }


def make_json_safe(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None

    if isinstance(value,dict):
        return {
            str(key):make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value,(list,tuple)):
        return [make_json_safe(item) for item in value]
    
    if isinstance(value,np.generic):
        return make_json_safe(value.item())

    if isinstance(value,float) and not math.isfinite(value):
        return None

    if isinstance(value,(date,datetime)):
        return value.isoformat()

    return value


def process_features(gdf):
    features = []

    if gdf.crs is None:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file does not contain a CRS."
        )

    crs = gdf.crs.to_string()

    for index, row in gdf.iterrows():
        geometry = row.geometry

        if geometry is None or geometry.is_empty:
            measurement = {
                "type": None,
                "value": None,
                "unit": None,
                "status": "EMPTY_GEOMETRY"
            }
        else:
            measurement = calculate_measurement(
                geometry,
                gdf.crs
            )

        feature = {
            "feature_id": index,
            "geometry_type": geometry.geom_type if geometry else None,
            "geometry": mapping(geometry) if geometry else None,
            "crs": crs,
            "properties": {
                key:make_json_safe(value)
                for key,value in row.drop(labels="geometry").to_dict().items()
            },
            "measurement": measurement
        }

        features.append(feature)

    return features


def extract_zip_safely(zip_path: Path, destination: Path):
    destination = destination.resolve()

    with zipfile.ZipFile(zip_path, "r") as zip_file:
        members = zip_file.infolist()

        # Limit the number of entries in the ZIP
        if len(members) > MAX_ZIP_MEMBERS:
            raise HTTPException(
                status_code=400,
                detail="The ZIP contains too many files."
            )

        # Limit the total uncompressed size
        total_size = sum(member.file_size for member in members)

        if total_size > MAX_UNCOMPRESSED_SIZE:
            raise HTTPException(
                status_code=413,
                detail="The ZIP file is too large after extraction."
            )

        for member in members:
            member_path = (destination / member.filename).resolve()

            if not (
                member_path == destination
                or str(member_path).startswith(str(destination) + "/")
            ):
                raise HTTPException(
                    status_code=400,
                    detail="The ZIP file contains an unsafe file path."
                )

            # Reject symbolic links
            mode = (member.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise HTTPException(
                    status_code=400,
                    detail="The ZIP file contains an unsupported symbolic link."
                )

        try:
            zip_file.extractall(destination)
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            raise HTTPException(
                status_code=400,
                detail="The ZIP archive could not be extracted."
            ) from exc

    
@app.post("/api/files",status_code = status.HTTP_201_CREATED,response_model=FileInfoResponse)
async def upload_file(file:UploadFile):

    validate_extension(file)
    file_path = await save_upload(file)

    try:
        gdf, features = process_file(file_path)

        file_id = str(uuid.uuid4())

        files_store[file_id] = {
            "id": file_id,
            "filename": file.filename,
            "feature_count": len(features),
            "crs": gdf.crs.to_string(),
            "status": "COMPLETED",
            "features": features
        }

        return {
            "id": file_id,
            "filename": file.filename,
            "feature_count": len(features),
            "crs": gdf.crs.to_string(),
            "status": "COMPLETED"
        }

    finally:
        file_path.unlink(missing_ok=True)


@app.get("/api/files/{file_id}",response_model=FileInfoResponse)
async def get_file_info(file_id: str):

    file_record = files_store.get(file_id)

    if file_record is None:
        raise HTTPException(
            status_code=404,
            detail="File not found."
        )

    return {
        "id": file_record["id"],
        "filename": file_record["filename"],
        "feature_count": file_record["feature_count"],
        "crs": file_record["crs"],
        "status": file_record["status"]
    }


@app.get("/api/files/{file_id}/features",response_model=list[FeatureResponse])
async def get_features(file_id:str):
    file_record = files_store.get(file_id)
    if file_record is None:
        raise HTTPException(
            status_code =404,
            detail ="File not found."
        )

    return file_record["features"]


@app.get("/api/files/{file_id}/measurements",response_model=MeasurementsResponse)
async def get_measurements(file_id: str):

    file_record = files_store.get(file_id)

    if file_record is None:
        raise HTTPException(
            status_code=404,
            detail="File not found."
        )

    return {
        "file_id": file_record["id"],
        "filename": file_record["filename"],
        "features": [
            {
                "feature_id": feature["feature_id"],
                "geometry_type": feature["geometry_type"],
                "measurement": feature["measurement"]
            }
            for feature in file_record["features"]
        ]
    }