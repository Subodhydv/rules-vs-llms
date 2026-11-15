"""SYNTHETIC stand-in for the NYC 311 sample — for unit tests and offline smoke runs ONLY.

Same schema and plausible value distributions (agencies, complaint/descriptor pairs, ZIP->borough, coordinates,
templated resolutions), plus a small rate of the kinds of quality problems seen in the real data. Every
report generated from it carries a "SYNTHETIC FIXTURE" banner. Real results come from fetch_data.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TYPES = {  # agency: {complaint_type: [descriptors]}
    "NYPD": {"Noise - Residential": ["Loud Music/Party", "Banging/Pounding", "Loud Talking", "Loud Television"],
             "Illegal Parking": ["Blocked Hydrant", "Double Parked Blocking Traffic", "Posted Parking Sign Violation",
                                 "Blocked Sidewalk"],
             "Blocked Driveway": ["No Access", "Partial Access"],
             "Noise - Street/Sidewalk": ["Loud Music/Party", "Loud Talking"],
             "Abandoned Vehicle": ["With License Plate", "Without License Plate"]},
    "HPD": {"HEAT/HOT WATER": ["ENTIRE BUILDING", "APARTMENT ONLY"],
            "PLUMBING": ["WATER SUPPLY", "TOILET", "BATHTUB/SHOWER"],
            "UNSANITARY CONDITION": ["PESTS", "MOLD", "GARBAGE"],
            "PAINT/PLASTER": ["WALL", "CEILING"]},
    "DSNY": {"Dirty Condition": ["Trash", "Dumping"], "Missed Collection": ["Trash", "Recycling - Paper"]},
    "DOT": {"Street Condition": ["Pothole", "Cave-in", "Defective Hardware"],
            "Street Light Condition": ["Street Light Out", "Street Light Cycling"]},
    "DEP": {"Water System": ["Hydrant Running (WC3)", "Leak (Use Comments) (WA2)"],
            "Noise": ["Noise: Construction Before/After Hours (NM1)", "Noise: Jack Hammering (NC2)"]},
    "DOHMH": {"Rodent": ["Rat Sighting", "Signs of Rodents", "Mouse Sighting"],
              "Food Establishment": ["Food Contaminated", "Pests/Unsanitary Conditions"]},
    "DPR": {"Damaged Tree": ["Branch Cracked and Will Fall", "Trunk Damaged"],
            "Overgrown Tree/Branches": ["Blocking Street", "Hitting Building"]},
}
AGENCY_WEIGHTS = {"NYPD": 0.38, "HPD": 0.22, "DSNY": 0.1, "DOT": 0.1, "DEP": 0.07, "DOHMH": 0.06, "DPR": 0.07}
CLOSED_TEXT = {
    "NYPD": ["The Police Department responded to the complaint and took action to fix the condition.",
             "The Police Department responded and upon arrival those responsible for the condition were gone.",
             "The Police Department responded to the complaint and determined that police action was not necessary."],
    "HPD": ["The Department of Housing Preservation and Development inspected the condition and issued a violation.",
            "The complaint you filed is a duplicate of a condition already reported by another tenant.",
            "HPD contacted a tenant who verified that the condition was corrected."],
    "DSNY": ["The Department of Sanitation investigated this complaint and cleaned the location.",
             "The Department of Sanitation collected the material."],
    "DOT": ["The Department of Transportation inspected this complaint and repaired the problem.",
            "The Department of Transportation inspected the condition and found no problem."],
    "DEP": ["The Department of Environmental Protection inspected the condition and corrected it.",
            "DEP investigated and did not find a violation at this time."],
    "DOHMH": ["The Department of Health inspected the location and found signs of rodents; a notice was issued.",
              "This service request was closed because the Department of Health received an earlier complaint."],
    "DPR": ["Parks inspected the tree and completed the required work.",
            "Parks inspected the location and determined no work is needed."],
}
OPEN_TEXT = ["The complaint has been received and is being reviewed by the agency.",
             "This complaint has been assigned to an inspector and a visit will be scheduled.",
             "The agency is still working on this request; please check back for updates."]
ZIPS = {"MANHATTAN": [f"100{i:02d}" for i in range(1, 41)] + ["10128", "10280"],
        "BRONX": [f"104{i:02d}" for i in range(51, 76)],
        "BROOKLYN": [f"112{i:02d}" for i in range(1, 40)],
        "QUEENS": [f"113{i:02d}" for i in range(54, 80)] + [f"114{i:02d}" for i in range(11, 36)],
        "STATEN ISLAND": [f"103{i:02d}" for i in range(1, 15)]}
CENTRE = {"MANHATTAN": (40.78, -73.97, 0.03, 0.015), "BRONX": (40.84, -73.88, 0.025, 0.03),
          "BROOKLYN": (40.65, -73.95, 0.03, 0.035), "QUEENS": (40.72, -73.82, 0.04, 0.06),
          "STATEN ISLAND": (40.58, -74.15, 0.03, 0.04)}
STREETS = ["BROADWAY", "AVENUE A", "WEST 72 STREET", "OCEAN AVENUE", "JAMAICA AVENUE", "GRAND CONCOURSE",
           "VICTORY BOULEVARD", "ATLANTIC AVENUE", "QUEENS BOULEVARD", "FLATBUSH AVENUE", "LENOX AVENUE"]


def make(n: int = 60000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    agencies = [str(a) for a in rng.choice(list(AGENCY_WEIGHTS), size=n, p=list(AGENCY_WEIGHTS.values()))]
    boroughs = [str(b) for b in rng.choice(list(ZIPS), size=n, p=[0.22, 0.2, 0.3, 0.23, 0.05])]
    start = np.datetime64("2023-01-01T00:00:00")
    created = start + rng.integers(0, 365 * 86400, size=n).astype("timedelta64[s]")
    dur = (rng.lognormal(10, 1.6, size=n)).astype("int64")
    rows = []
    for i in range(n):
        ag, bo = agencies[i], boroughs[i]
        ct = str(rng.choice(list(TYPES[ag])))
        de = str(rng.choice(TYPES[ag][ct]))
        lat0, lon0, slat, slon = CENTRE[bo]
        closed = rng.random() > 0.04
        cdt = str(created[i])
        rows.append({
            "unique_key": 56000000 + i, "created_date": cdt + ".000",
            "closed_date": (str(created[i] + np.timedelta64(int(dur[i]), "s")) + ".000") if closed else None,
            "agency": ag, "complaint_type": ct, "descriptor": de,
            "location_type": rng.choice(["Street/Sidewalk", "Residential Building/House", "RESIDENTIAL BUILDING"]),
            "incident_zip": rng.choice(ZIPS[bo]),
            "incident_address": f"{rng.integers(1, 3000)} {rng.choice(STREETS)}",
            "borough": bo, "status": "Closed" if closed else rng.choice(["Open", "In Progress", "Assigned"]),
            "resolution_description": rng.choice(CLOSED_TEXT[ag]) if closed else rng.choice(OPEN_TEXT),
            "latitude": round(float(rng.normal(lat0, slat)), 6), "longitude": round(float(rng.normal(lon0, slon)), 6),
            "open_data_channel_type": rng.choice(["ONLINE", "PHONE", "MOBILE", "UNKNOWN"]),
        })
    df = pd.DataFrame(rows)
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: str(v) if isinstance(v, np.str_) else v)
    # naturally occurring problems, at rates similar to the real 2023 data (see SoQL snapshot)
    k = lambda r: rng.random(n) < r  # noqa: E731
    m = k(0.0013) & df.closed_date.notna()
    df.loc[m, "closed_date"] = (pd.to_datetime(df.loc[m, "created_date"]) - pd.Timedelta(hours=3)).dt.strftime(
        "%Y-%m-%dT%H:%M:%S.000")
    m = k(0.019) & df.closed_date.notna()
    df.loc[m, "closed_date"] = df.loc[m, "created_date"]
    df.loc[k(0.015), ["latitude", "longitude"]] = np.nan
    df.loc[k(0.012), "incident_zip"] = None
    df.loc[k(0.002), "borough"] = "Unspecified"
    df.loc[k(0.001), "incident_zip"] = "00000"
    dup = rng.choice(n, size=int(n * 0.002), replace=False)
    df = pd.concat([df, df.iloc[dup].assign(unique_key=lambda d: d.unique_key + 10_000_000)], ignore_index=True)
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)
