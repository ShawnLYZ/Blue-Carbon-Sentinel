# Kuala Selangor satellite dataset

[Download the dataset ZIP](Kuala-Selangor-Sentinel-2-Dataset.zip) (approximately 3.5 MB). The archive includes a full data guide and file checksums.

## Scope

The Mission Control satellite preview uses a **500 × 500 m study footprint** (25 ha) around **3.33656° N, 101.23674° E**, Kuala Selangor Nature Park. This dataset does not cover the entire district or define farm ownership boundaries.

Source: **Copernicus Sentinel-2 Level-2A**, **MSI** instrument, distributed through **Earth Search / Element 84 and AWS Open Data**, collection `sentinel-2-l2a`, tile `47NQD`.

## Contents

- **20 acquisitions shown in the app**, 31 July–14 October 2026, with cropped GeoTIFFs, RGB previews, pixel CSVs, red/NIR digital numbers, scene classification, derived NDVI and the usable-clear-land mask.
- **887 matching archive records**, 14 January 2017–14 October 2026, with complete returned STAC metadata and original asset download links. Full-resolution imagery for all 887 historical records is not bundled.
- Satellite identities and timestamps for every scene. Archive counts: **399 Sentinel-2A, 423 Sentinel-2B, 65 Sentinel-2C**.
- Study-area GeoJSON, observation quality, source scale/offset metadata and checksums.

The browser-selected observation at export was **Sentinel-2C, 4 September 2026 at 11:47 am MYT**, scene `S2C_47NQD_20260904_0_L2A`. This records the selection at export, not the app's permanent default.

## Interpretation

The exports reproduce the app's 50 × 50 output grid at approximately 10 m sampling. Scene classification has a native 20 m resolution and is resampled. Enlarging an image adds no new detail. NDVI is derived from red and near-infrared reflectance, with masked pixels retained as no data.

Water/soil sliders, procedural trees, wellness scores and simulated carbon eligibility are separate from these satellite observations. This collection contains no Sentinel-1 radar input.

## Provenance

Catalogue snapshot retrieved **17 October 2026 UTC**. Archive scope means all matching records returned by this app's collection and footprint, not every Sentinel product in every catalogue. See the ZIP's `README.md` and `dataset-summary.json` for extraction, units, limitations and pagination provenance.

Contains modified Copernicus Sentinel data.

- [ESA Sentinel-2 mission](https://www.esa.int/Applications/Observing_the_Earth/Copernicus/Sentinel-2)
- [Copernicus product definitions](https://sentiwiki.copernicus.eu/web/s2-products)
- [Earth Search collection documentation](https://github.com/Element84/earth-search)
- [AWS open dataset](https://registry.opendata.aws/sentinel-2-l2a-cogs/)
