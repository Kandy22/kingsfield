/**
 * Media Route — serves audio and video assets from the assets/ directory.
 *
 * Supports range requests (required for audio/video seeking in browsers).
 * In production, swap local file serving for S3 pre-signed URL redirects
 * using the existing storage.ts layer.
 *
 * Routes:
 *   GET /api/media/audio/:folder/:file  — serve from assets/audio/
 *   GET /api/media/music/:folder/:file  — serve from assets/music/
 *   GET /api/media/music/:file          — serve from assets/music/ (root)
 *   GET /api/media/video/:file          — serve from assets/videos/
 *   GET /api/media/catalog              — returns JSON playlist catalog
 */

import { Router, Request, Response } from 'express';
import path from 'node:path';
import fs from 'node:fs';

export const mediaRouter = Router();

// ── ASSET ROOT ────────────────────────────────────────────────────────────────
const ASSETS_ROOT = path.resolve(process.cwd(), '..', 'assets');

// ── MIME TYPES ────────────────────────────────────────────────────────────────
const MIME: Record<string, string> = {
  '.mp3':  'audio/mpeg',
  '.mp4':  'video/mp4',
  '.m4a':  'audio/mp4',
  '.ogg':  'audio/ogg',
  '.wav':  'audio/wav',
  '.webm': 'video/webm',
};

// ── HELPERS ───────────────────────────────────────────────────────────────────
function serveMedia(filePath: string, req: Request, res: Response) {
  if (!fs.existsSync(filePath)) {
    return res.status(404).json({ error: 'Media not found' });
  }

  const ext  = path.extname(filePath).toLowerCase();
  const mime = MIME[ext] ?? 'application/octet-stream';
  const stat = fs.statSync(filePath);
  const size = stat.size;

  // Range request support — required for audio/video seeking
  const range = req.headers.range;
  if (range) {
    const [startStr, endStr] = range.replace(/bytes=/, '').split('-');
    const start = parseInt(startStr, 10);
    const end   = endStr ? parseInt(endStr, 10) : size - 1;
    const chunkSize = end - start + 1;

    res.writeHead(206, {
      'Content-Range':  `bytes ${start}-${end}/${size}`,
      'Accept-Ranges':  'bytes',
      'Content-Length': chunkSize,
      'Content-Type':   mime,
      'Cache-Control':  'public, max-age=3600',
    });
    fs.createReadStream(filePath, { start, end }).pipe(res);
  } else {
    res.writeHead(200, {
      'Content-Length': size,
      'Content-Type':   mime,
      'Accept-Ranges':  'bytes',
      'Cache-Control':  'public, max-age=3600',
    });
    fs.createReadStream(filePath).pipe(res);
  }
}

// Sanitize path segments — prevent directory traversal
function safe(...segments: string[]): string {
  const joined = path.join(...segments);
  if (joined.includes('..')) throw new Error('Invalid path');
  return joined;
}

// ── ROUTES ────────────────────────────────────────────────────────────────────

// Audio clips (short branded clips, ElevenLabs voices)
mediaRouter.get('/audio/:file', (req, res) => {
  try {
    const filePath = path.join(ASSETS_ROOT, 'audio', safe(req.params.file));
    serveMedia(filePath, req, res);
  } catch { res.status(400).json({ error: 'Invalid path' }); }
});

// Audio with subfolder (e.g. /audio/god level closing arguments/file.mp3)
mediaRouter.get('/audio/:folder/:file', (req, res) => {
  try {
    const filePath = path.join(ASSETS_ROOT, 'audio', safe(req.params.folder, req.params.file));
    serveMedia(filePath, req, res);
  } catch { res.status(400).json({ error: 'Invalid path' }); }
});

// Music tracks (root of music/)
mediaRouter.get('/music/:file', (req, res) => {
  try {
    const filePath = path.join(ASSETS_ROOT, 'music', safe(req.params.file));
    serveMedia(filePath, req, res);
  } catch { res.status(400).json({ error: 'Invalid path' }); }
});

// Music with subfolder (e.g. /music/Guillotine- Rock/file.mp3)
mediaRouter.get('/music/:folder/:file', (req, res) => {
  try {
    const filePath = path.join(ASSETS_ROOT, 'music', safe(req.params.folder, req.params.file));
    serveMedia(filePath, req, res);
  } catch { res.status(400).json({ error: 'Invalid path' }); }
});

// Video
mediaRouter.get('/video/:file', (req, res) => {
  try {
    const filePath = path.join(ASSETS_ROOT, 'videos', safe(req.params.file));
    serveMedia(filePath, req, res);
  } catch { res.status(400).json({ error: 'Invalid path' }); }
});

// ── CATALOG ───────────────────────────────────────────────────────────────────
// Returns the full playlist so the frontend player knows what's available
// without hardcoding filenames.

mediaRouter.get('/catalog', (_req, res) => {
  const catalog = buildCatalog();
  res.json(catalog);
});

interface Track {
  id:       string;
  title:    string;
  category: 'ambient' | 'event' | 'voice' | 'video';
  url:      string;
  duration?: string;
}

function buildCatalog(): { ambient: Track[]; events: Track[]; voices: Track[] } {
  // Curated catalog — add/remove tracks here as assets evolve.
  // URLs map to the routes above (relative to /api/media/).

  const ambient: Track[] = [
    { id: 'guillotine-hard',   title: 'Guillotine (Hard)',      category: 'ambient', url: '/api/media/music/Guillotine- Rock/Guillotine  (4) HARD GOOD 1min59.mp3' },
    { id: 'guillotine-house',  title: 'Guillotine (House)',     category: 'ambient', url: '/api/media/music/Gillotine- House/Guill1otin1e HOUSE GOOD 3min42 .mp3' },
    { id: 'guillotine-pop',    title: 'Guillotine (Pop/Bass)',  category: 'ambient', url: '/api/media/music/Gullotine- General/Guillotine -POPBASS-CanISeitoff GOOD (7).mp3' },
    { id: 'lawyers-guns',      title: 'Lawyers, Guns & Money', category: 'ambient', url: '/api/media/music/Lawyers, Guns & Money/AlgoTLE Free Nav v3.mp3' },
    { id: 'sunshine-hustle',   title: 'Sunshine Hustle',       category: 'ambient', url: '/api/media/music/Sunshine Hustle 1min 48sec Algo Bassish .mp3' },
    { id: 'thecourts',         title: 'The Courts',            category: 'ambient', url: '/api/media/music/TheCo1urts.mp3' },
  ];

  const events: Track[] = [
    { id: 'trust-verify',      title: 'Trust But Verify',          category: 'event', url: '/api/media/audio/Trust But Verify 9sec.mp3',                    duration: '9s' },
    { id: 'welcome-goliath',   title: 'Welcome to Goliath',        category: 'event', url: '/api/media/audio/Welcome to Goliath 11sec.mp3',                 duration: '11s' },
    { id: 'enemy-strong',      title: 'The Enemy Is Strong',       category: 'event', url: '/api/media/audio/The enemy is strong.mp3' },
    { id: 'battles-win',       title: 'There Are Battles You Must Win', category: 'event', url: '/api/media/audio/There are some battles you must win.mp3' },
    { id: 'prepare-dazzled',   title: 'Prepare to Be Dazzled',     category: 'event', url: '/api/media/audio/Prepare to be dazzled 3 sec.mp3',              duration: '3s' },
  ];

  const voices: Track[] = [
    { id: 'kingsfield-intro',  title: 'Kingsfield Intro (Orsen)',  category: 'voice', url: '/api/media/audio/Kingsfield Lawfare Audio Intro/ElevenLabs_2024-05-06T20_53_13_Orsen_ivc_s47_sb82_se16_b_m2.mp3' },
    { id: 'storm-brewing',     title: "There's a Storm Brewing",   category: 'voice', url: '/api/media/audio/god level closing arguements/There_s a storm brewing v2.mp3' },
    { id: 'courts-colorado',   title: 'Courts of Colorado',        category: 'voice', url: '/api/media/audio/The Courts of Colorado.mp3' },
  ];

  return { ambient, events, voices };
}
