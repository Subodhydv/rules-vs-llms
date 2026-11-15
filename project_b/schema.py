"""The batch contract for NYC 311 data entering the data-quality layer.

A batch is a pandas DataFrame with these columns and dtypes (dates are kept as the ISO strings the API
delivers, because a date-format switch must be detectable at ingestion).
"""
COLUMNS = {
    "unique_key": "int64",
    "created_date": "object",
    "closed_date": "object",
    "agency": "object",
    "complaint_type": "object",
    "descriptor": "object",
    "location_type": "object",
    "incident_zip": "object",
    "incident_address": "object",
    "borough": "object",
    "status": "object",
    "resolution_description": "object",
    "latitude": "float64",
    "longitude": "float64",
    "open_data_channel_type": "object",
}
NUMERIC = ["unique_key", "latitude", "longitude"]
TEXT = ["descriptor", "resolution_description"]
ISO_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?$"
# Bounding box of the five boroughs (generous by ~1 km)
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 40.47, 40.93, -74.27, -73.68
BOROUGHS = ["MANHATTAN", "BROOKLYN", "QUEENS", "BRONX", "STATEN ISLAND"]
OPEN_STATUSES = {"Open", "In Progress", "Assigned", "Pending", "Started"}
