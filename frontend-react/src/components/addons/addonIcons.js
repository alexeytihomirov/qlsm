// Icons an addon manifest may name, resolved from a fixed allow-list.
//
// An allow-list rather than a lookup into all of lucide-react for two
// reasons: it keeps the icon set coherent with the rest of QLSM, and it means
// a manifest string is never used to reach into a module namespace.
import {
  Activity, Archive, Boxes, Database, Download, Film, Gauge, Globe, Layers,
  Puzzle, Radio, Settings, Share2, Terminal, Upload, Wrench, Zap,
} from 'lucide-react';

const ICONS = {
  activity: Activity,
  archive: Archive,
  boxes: Boxes,
  database: Database,
  download: Download,
  film: Film,
  gauge: Gauge,
  globe: Globe,
  layers: Layers,
  puzzle: Puzzle,
  radio: Radio,
  settings: Settings,
  share: Share2,
  terminal: Terminal,
  upload: Upload,
  wrench: Wrench,
  zap: Zap,
};

export const DEFAULT_ADDON_ICON = Puzzle;

export function resolveAddonIcon(name) {
  if (typeof name !== 'string') return DEFAULT_ADDON_ICON;
  return ICONS[name.trim().toLowerCase()] || DEFAULT_ADDON_ICON;
}

export default ICONS;
