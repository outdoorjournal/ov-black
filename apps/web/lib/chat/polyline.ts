// Google encoded-polyline decoder (precision 1e5).
//
// The route surface receives geometry as the `encodedPolyline` string Google
// Routes returns; decoding client-side keeps the SSE frame small (a few KB of
// string instead of thousands of coordinate pairs). Returns [lng, lat] pairs —
// GeoJSON / Mapbox order — ready to drop into a LineString.
//
// Reference algorithm:
// https://developers.google.com/maps/documentation/utilities/polylinealgorithm

export type LngLat = [number, number];

export function decodePolyline(encoded: string): LngLat[] {
  const coords: LngLat[] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;

  while (index < encoded.length) {
    let result = 0;
    let shift = 0;
    let byte: number;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      if (Number.isNaN(byte) || byte < 0) return coords; // truncated input — keep what we have
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lat += result & 1 ? ~(result >> 1) : result >> 1;

    result = 0;
    shift = 0;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      if (Number.isNaN(byte) || byte < 0) return coords;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lng += result & 1 ? ~(result >> 1) : result >> 1;

    coords.push([lng / 1e5, lat / 1e5]);
  }
  return coords;
}
