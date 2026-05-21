/**
 * Service for map-related operations using OpenStreetMap and OSRM
 */

/**
 * Fetches a driving route between two points using OSRM
 * @param {Object} start - {lat, lng}
 * @param {Object} end - {lat, lng}
 * @returns {Promise<Array>} Array of [lat, lng] coordinates
 */
export const getRoute = async (start, end) => {
  if (!start || !end) return [];
  
  try {
    // OSRM expects coordinates as {lng},{lat};{lng},{lat}
    const url = `https://router.project-osrm.org/route/v1/driving/${start.lng},${start.lat};${end.lng},${end.lat}?overview=full&geometries=geojson`;

    const res = await fetch(url);
    const data = await res.json();

    if (!data.routes || !data.routes.length) {
      console.warn("No route found between", start, "and", end);
      return [];
    }

    // OSRM returns GeoJSON coordinates as [lng, lat]
    const coordinates = data.routes[0].geometry.coordinates;

    // Convert [lng, lat] → [lat, lng] for Leaflet
    return coordinates.map(([lng, lat]) => [lat, lng]);
  } catch (error) {
    console.error("Error fetching OSRM route:", error);
    return [];
  }
};
