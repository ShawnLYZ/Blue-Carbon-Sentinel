# Blue Carbon Sentinel: frontend demo

A clickable demo of Blue Carbon Sentinel, which watches the mangrove forest of Kuala Selangor Nature Park, Malaysia.

This folder is **only the website**. There is no server, database or real hardware. The nine sensor readings, the camera and the replanting scan are simulated in the browser, so the demo always works and never depends on a board being plugged in. The small **Demo data** badge in the top bar says so.

## Start the demo

1. Double-click **`start.cmd`**.
2. The first time, it installs what it needs. This takes about a minute and needs the internet.
3. Your browser opens at **http://localhost:5173**. Chrome is recommended.
4. To stop the demo, close the black window.

You need [Node.js](https://nodejs.org) installed (version 20 or newer). The maps also need the internet, because the satellite images come from Mapbox.

## The four pages

Press the number keys **1 to 4** to jump between pages.

| # | Page | What it shows |
|---|---|---|
| 1 | **Command Center** | A satellite globe of Malaysia. Kuala Selangor is live; four more sites are coming soon. Press **Fly to Kuala Selangor** to fly down to the forest. |
| 2 | **Satellite Intelligence** | Left: the real satellite image of the 500 × 500 m forest square. Right: a 3D model of the same forest, with trees exactly where the image shows forest. Drag to turn, scroll to zoom, double-click to look closer. |
| 3 | **Sentinel Network** | The forest's health right now: nine sensor cards, the camera and the station map. This is where the two highlight buttons are. |
| 4 | **Digital Twin** | The 3D forest again. Choose a colour layer at the top, then point anywhere to read the latitude, longitude and all nine sensors at that exact spot. Click to pin the card; press Esc to release it. |

## Demo script

1. **Command Center:** "Here are our mangrove sites. Kuala Selangor is live; four more are coming." Point at the three tiles, then press **Fly to Kuala Selangor**.
2. **Satellite Intelligence:** "On the left is the real satellite image; on the right, our 3D model of the same forest." Zoom in on the stilt roots.
3. **Sentinel Network, Prevention:** press **Simulate danger**. The readings slide from Healthy to Warning to Danger in about 10 seconds. The camera is asked for a photo automatically and the photo appears about 10 seconds later. Press **Restore healthy**.
4. **Sentinel Network, Replantation:** press **Scan for replanting**. "The satellite found an empty patch where conditions are healthy. About 6,590 seedlings fit here."
5. **Digital Twin:** point anywhere. Switch between sensor layers and show the planted patch. Try it during danger: the area around the station turns red.
6. Afterwards: **⋯ → Reset demo**, ready for the next audience. Camera photos are kept.

## Camera photos

There is no real camera in this demo, so the "camera" uses photos from a folder:

- By default it uses four freely licensed mangrove photos, labelled **Sample photo** on screen. Their sources and licences are in `public/sample-photos/SOURCES.md`, and each photo's credit shows when you open it full size.
- **To use your own ESP32-CAM photos**, put JPG files in the **`camera-photos`** folder. The demo uses them instead (labelled **ESP32-CAM photo**) as soon as you save them. No restart needed.
- If no photos are available at all, the camera panel shows the honest "Camera offline, no new photo" message with a **Try again** button.

## Good to know

- The demo remembers the danger state, planted patches and photos in this browser, so a reload does not break the story. **⋯ → Reset demo** starts fresh.
- **"Another program is already using http://localhost:5173"?** Another website project is running on the same address (for example the ESP32 Sensors dashboard). Close its window, then double-click `start.cmd` again.
- **Satellite image unavailable?** Check the internet connection. The Mapbox key lives in the file `.env.local` (`VITE_MAPBOX_TOKEN=...`); a blank copy is in `.env.example`.
- **3D view unavailable?** Use Chrome with hardware acceleration turned on (Settings → System).
- The 3D forest lowers its quality by itself if the computer struggles, so it keeps running smoothly.
- The forest outlines were traced once from the Mapbox satellite image for this non-commercial project. Only the outlines are stored, never Mapbox images.

## For developers

```
npm install
npm run dev         # http://localhost:5173
npm run typecheck
npm run build       # static build in dist/
```

- `src/sim/`: the Sensor Engine (Ranges, ramps, Level) and the Field Model (values at any point).
- `src/forest/`: the Canopy Map, Forest Model (in a Web Worker) and the three.js Forest Scene.
- `src/maps/`: Mapbox globe and satellite maps. `src/pages/`: the four pages. `src/state/store.ts`: app-wide state and the simulated camera.
- `src/site/canopyOutlines.ts`: the traced canopy and water outlines, the Sentinel Station and the three Replant Patches.
