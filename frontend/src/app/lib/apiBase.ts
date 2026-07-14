/**
 * Backend origin for browser clients.
 * Prefer NEXT_PUBLIC_API_BASE_URL when set; otherwise use the same host the
 * page was opened from so LAN devices (http://192.168.x.x:3000) call
 * http://192.168.x.x:3001 instead of the device's own localhost.
 */
export function getApiBase(): string {
    const fromEnv = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
    if (fromEnv) return fromEnv.replace(/\/$/, "");
    if (typeof window !== "undefined" && window.location?.hostname) {
        return `http://${window.location.hostname}:3001`;
    }
    return "http://localhost:3001";
}
