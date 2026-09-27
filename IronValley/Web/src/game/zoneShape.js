// Control zone shapes shared by the match session (presence), the AI (posts, urgency) and the zone view.
//   cylinder: { center: [x, y, z], radius, height }       feet within the radius and y in [center.y - 0.5, center.y + height]
//   polygon:  { polygon: [[x, z], ...], yMin, yMax, ... }  feet inside the polygon (XZ) and yMin <= y <= yMax
//             (Docs/MAP_DESIGN.md zones: capsule foot point inside `polygon` and z_min <= z_foot <= z_max)
// No three.js dependency: points are { x, y, z }.

/** Is (x, z) inside the polygon [[x, z], ...] (even-odd rule)? */
export function pointInPolygonXZ(poly, x, z) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0];
    const zi = poly[i][1];
    const xj = poly[j][0];
    const zj = poly[j][1];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

/** Feet position p inside zone z. */
export function pointInZone(p, z) {
  if (!z) return false;
  if (Array.isArray(z.polygon) && z.polygon.length >= 3) {
    const y0 = z.yMin ?? z.center[1] - 0.5;
    const y1 = z.yMax ?? z.center[1] + (z.height ?? 4);
    return p.y >= y0 && p.y <= y1 && pointInPolygonXZ(z.polygon, p.x, p.z);
  }
  const dx = p.x - z.center[0];
  const dz = p.z - z.center[2];
  const h = z.height ?? 4;
  return dx * dx + dz * dz <= z.radius * z.radius && p.y >= z.center[1] - 0.5 && p.y <= z.center[1] + h;
}

/** Signed horizontal distance from p to the zone outline (negative inside); cylinder: distance to the circle. */
export function zoneEdgeDistance(p, z) {
  if (Array.isArray(z.polygon) && z.polygon.length >= 3) {
    let d = Infinity;
    const P = z.polygon;
    for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
      const ax = P[j][0];
      const az = P[j][1];
      const bx = P[i][0];
      const bz = P[i][1];
      const dx = bx - ax;
      const dz = bz - az;
      const L2 = dx * dx + dz * dz;
      const t = L2 > 1e-12 ? Math.max(0, Math.min(1, ((p.x - ax) * dx + (p.z - az) * dz) / L2)) : 0;
      d = Math.min(d, Math.hypot(p.x - (ax + t * dx), p.z - (az + t * dz)));
    }
    return pointInPolygonXZ(P, p.x, p.z) ? -d : d;
  }
  return Math.hypot(p.x - z.center[0], p.z - z.center[2]) - z.radius;
}
